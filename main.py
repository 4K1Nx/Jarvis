"""Viv — assistente de voz em tempo real.

    python main.py            inicia a Viv completa e abre a HUD
    python main.py --demo     só a HUD, com eventos de demonstração (sem microfone nem rede)
    python main.py --no-hud   não abre a janela da HUD
"""
import argparse
import asyncio
import os
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

os.chdir(Path(__file__).resolve().parent)

from viv.bus import BUS  # noqa: E402
from viv.live import MissingKey, State, Viv  # noqa: E402


@dataclass
class Parts:
    viv: Any
    gate: Any
    memory: Any
    reminders: Any
    audio: Any
    speaker: Any
    watcher: Any
    app: Any
    settings: Any = None
    routine: Any = None
    watch: Any = None
    relations: Any = None
    gowa: Any = None


NOTICE_GAP = 120                   # s: mensagens seguidas da mesma conversa geram um aviso só
RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}     # códigos de chuva da Open-Meteo


def load_config() -> dict:
    with open("config.yaml", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def make_client(cfg: dict):
    """Devolve (cliente, connect). Sem chave, connect levanta MissingKey ao ser chamado."""
    live = cfg.get("live", {})
    key = os.environ.get(live.get("api_key_env", "GEMINI_API_KEY"), "").strip()
    if not key:
        def no_key(config):
            raise MissingKey()
        return None, no_key
    from google import genai
    client = genai.Client(api_key=key, http_options={"api_version": live.get("api_version", "v1beta")})
    model = live.get("model", "gemini-3.8-live")
    return client, lambda config: client.aio.live.connect(model=model, config=config)


def build(cfg: dict, connect, audio=None, client=None) -> Parts:
    from server import create_app
    from viv.audit import Audit
    from viv.gaps import CapabilityGaps
    from viv.memory import Memory
    from viv.mood import Mood
    from viv.people import People
    from viv.relations import Relations, RelationsClock
    from viv.gowa import Gowa
    from viv.remote import Remote
    from viv.reminders import Reminders
    from viv.safety import Gate
    from viv.speaker import Speaker
    from viv.tools.registry import Context
    from viv.wake import WakeWatcher
    from viv import autostart
    from viv.routine import RoutineClock
    from viv.settings import Settings
    from viv.tools import vision
    from viv.watch import ScreenWatch
    settings = Settings(cfg.get("settings", {}).get("path", "data/viv_config.json"), cfg)
    settings.overlay(cfg)                 # antes de criar o áudio: fones e sensibilidade salvos valem ao abrir
    if audio is None:
        from viv.audio import AudioIO
        audio = AudioIO(cfg)
    cfg.setdefault("assistant", {}).update(user_name=settings.get("usuario.nome"), user_city=settings.get("usuario.cidade"))
    memory = Memory(cfg["memory"]["path"])
    speaker = Speaker(cfg)
    mood = Mood(enabled=settings.get("humor.ativo"), refusals=settings.get("humor.recusa"))
    people = People()
    relations = Relations(label=people.label)

    noticed: dict[str, float] = {}

    def new_message(jid, name, kind="texto", text=""):
        """Mensagem nova no WhatsApp. Um comando /viv (contato administrador, bloqueio) vai para
        viv/remote.py e não vira aviso. Dormindo, a Viv só mostra a notificação na tela; acordada,
        também avisa falando. Nunca diz o conteúdo por conta própria. Várias mensagens seguidas da
        mesma conversa geram um aviso só."""
        if remote.handle(jid, name, text, ctx, gowa.send):
            return
        if not settings.get("whatsapp.avisar_novas"):
            return
        now = time.monotonic()
        if now - noticed.get(jid, float("-inf")) < NOTICE_GAP:
            return
        noticed[jid] = now
        label = people.label(name)
        what = {"texto": "Mensagem nova", "foto": "Foto nova", "áudio": "Áudio novo", "vídeo": "Vídeo novo"}.get(
            kind, f"Nova mensagem ({kind})")
        BUS.emit("card", f"WhatsApp: {label}", kind="action", ok=True, wa=jid,
                 body=f"{what} na conversa com {label}. Clique para abrir.")
        viv.mention(f"Chegou agora no WhatsApp uma mensagem nova ({kind}) de {label}. Avise o usuário em uma frase "
                    "curta, sem inventar o conteúdo, e pergunte se ele quer que você leia. Se estiver no meio de outro "
                    "assunto, termine a frase antes.")
    gowa = Gowa(cfg, int(cfg.get("server", {}).get("port", 8765)), on_message=new_message)
    remote = Remote()
    ctx = Context(cfg, memory=memory, client=client, settings=settings, people=people, speaker=speaker, mood=mood,
                  relations=relations, gowa=gowa, audio=audio, remote=remote)
    gate = Gate(cfg, ctx, speaker, Audit(cfg), notify=lambda text: None)
    gate.mood = mood
    watcher = WakeWatcher(cfg, audio, on_wake=lambda reason: viv.wake(reason))
    viv = Viv(cfg, audio, gate, memory, watcher, connect, gaps=CapabilityGaps(),
              speaker=speaker, mood=mood, people=people)
    gate.notify = viv.notify
    reminders = Reminders(cfg["reminders"]["path"], viv.remind)
    reminders.deliver = lambda jid, text: gowa.send(jid, f"Viv: lembrete — {text}")
    ctx.reminders = reminders
    ctx.watch = ScreenWatch(lambda question: vision.look(ctx, question), viv.notify)

    def apply_setting(key, value):
        """Ajuste alterado pela HUD ou pela Viv passa a valer na hora."""
        if key == "hud.avatar":
            BUS.emit("hud", "", avatar=bool(value))
        elif key == "usuario.nome":
            cfg["assistant"]["user_name"] = value
        elif key == "usuario.cidade":
            cfg["assistant"]["user_city"] = value
        elif key == "audio.fones":
            audio.configure(headphones=value)
        elif key == "audio.sensibilidade_interrupcao":
            audio.configure(threshold=value)
        elif key == "conversa.segundos_ate_dormir":
            viv.idle_seconds = float(value)
        elif key == "ativacao.palmas":
            watcher.configure(clap=value)
        elif key == "ativacao.nome":
            watcher.configure(name=value)
        elif key == "inicio.com_windows":
            autostart.apply(value)
        elif key == "humor.ativo":
            mood.configure(enabled=value)
        elif key == "humor.recusa":
            mood.configure(refusals=value)
        elif key == "voz.nome":
            cfg.setdefault("live", {})["voice"] = value
    settings.on_change(apply_setting)
    app = create_app(viv, gate, audio, cfg, speaker, settings, mood, gowa)

    def private_notice(title, text):
        """Lembrete pessoal: por padrão só na tela; em voz alta se o usuário ligou."""
        if settings.get("relacoes.avisos_por_voz"):
            viv.notify(f"Lembrete privado do usuário — {title}: {text}")
        else:
            audio.beep("wake")
            BUS.emit("card", title, kind="content", format="texto", body=text, ok=True)

    def replied(contact):
        from viv.tools import whatsapp
        return whatsapp.replied(contact, ctx=ctx)

    def raining():
        from viv.tools import weather
        _, forecast = weather.fetch(settings.get("usuario.cidade"), settings.get("usuario.estado") or None)
        return int(forecast.get("current", {}).get("weather_code", 0)) in RAIN_CODES

    return Parts(viv, gate, memory, reminders, audio, speaker, watcher, app, settings,
                 RoutineClock(settings, viv.notify), ctx.watch,
                 RelationsClock(relations, settings, private_notice, replied, raining), gowa)


def welcome(parts: Parts, delay: float = 6.0) -> None:
    """Boas-vindas ao ligar o PC: painel "Resumo do dia" e relatório falado."""
    from viv import briefing
    from viv.errors import ERRORS
    from viv.tools import mail, weather
    time.sleep(delay)
    unread = (lambda: mail.unread_count(parts.settings)) if (parts.settings.get("email.usuario")
                                                             and os.environ.get("VIV_EMAIL_SENHA")) else None
    from viv.tools import whatsapp
    try:
        pending = whatsapp.pending_chats(parts.gate.ctx)
    except Exception as exc:                      # WhatsApp fora do ar não impede as boas-vindas
        ERRORS.record("boas-vindas", f"WhatsApp: {exc}")
        pending = None
    data = briefing.collect(parts.settings, parts.reminders, ERRORS, fetch_weather=weather.fetch, unread_count=unread,
                            whatsapp=pending)
    BUS.emit("card", "Resumo do dia", kind="content", format="tabela", body=briefing.panel(data), ok=True)
    if pending:
        BUS.emit("whatsapp", "WhatsApp", mode="lista", chats=pending)    # a tela acompanha quando ela citar cada um
    parts.viv.notify(briefing.prompt(data))


def toggle(viv) -> None:
    """Atalho global: acorda se dorme, põe para dormir se está acordada."""
    if viv.state in (State.SLEEPING, State.ERROR):
        viv.wake("hotkey")
    else:
        viv.sleep()


def open_hud(cfg: dict) -> None:
    url = f"http://127.0.0.1:{cfg['server']['port']}"
    try:
        subprocess.Popen(["cmd", "/c", "start", "", "msedge", f"--app={url}"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        webbrowser.open(url)


# ---- demonstração ---------------------------------------------------------
class DemoViv:
    def __init__(self):
        self.state = State.SLEEPING

    def wake(self, reason=""):
        pass

    def sleep(self):
        pass


class DemoGate:
    pending = None

    def on_click(self, accepted):
        BUS.emit("confirm_done", ok=accepted)


class DemoAudio:
    input_name = "Demonstração (sem microfone)"


def demo_loop(viv: DemoViv) -> None:
    import math
    script = [
        ("state", {"state": "listening"}, 2.5),
        ("transcript", {"text": "Viv, como está o computador?", "role": "user", "final": True}, .3),
        ("state", {"state": "thinking"}, 1.2),
        ("state", {"state": "executing"}, 1.0),
        ("card", {"text": "Estado do sistema", "kind": "data", "body": "CPU 12%, RAM 41%, disco 63% usado", "ok": True}, .4),
        ("state", {"state": "speaking"}, .1),
        ("transcript", {"text": "Tudo tranquilo por aqui: processador folgado e memória pela metade.", "role": "viv", "final": False}, 3.5),
        ("card", {"text": "Pesquisa: previsão do tempo", "kind": "search", "body": "Sol com poucas nuvens amanhã.", "ok": True,
                  "sources": [{"title": "Exemplo de fonte", "url": "https://example.com"}]}, 2.5),
        ("confirm", {"text": "Apagar: rascunho.txt (demonstração)", "name": "fs_delete", "args": {}, "seconds": 8}, 8.5),
        ("confirm_done", {"ok": False}, .5),
        ("state", {"state": "sleeping"}, 4.0),
    ]
    while True:
        for channel, extra, wait in script:
            extra = dict(extra)
            text = extra.pop("text", "")
            if channel == "state":
                viv.state = State(extra["state"])
            BUS.emit(channel, text, **extra)
            end = time.time() + wait
            while time.time() < end:
                wave = abs(math.sin(time.time() * 7)) * .5 + abs(math.sin(time.time() * 2.3)) * .4
                BUS.emit("level", value=wave, source="out" if viv.state == State.SPEAKING else "mic")
                time.sleep(.05)


def build_demo(cfg: dict):
    from server import create_app
    viv = DemoViv()
    return viv, create_app(viv, DemoGate(), DemoAudio(), cfg, None)


# ---- execução ---------------------------------------------------------------
def run_demo(cfg: dict, show: bool) -> None:
    from server import serve
    viv, app = build_demo(cfg)
    threading.Thread(target=demo_loop, args=(viv,), daemon=True).start()
    if show:
        threading.Timer(1.2, open_hud, args=(cfg,)).start()
    print(f"Demonstração da HUD em http://127.0.0.1:{cfg['server']['port']}  (Ctrl+C para sair)")
    serve(app, cfg)


def run_full(cfg: dict, show: bool, briefing: bool = False) -> int:
    from dotenv import load_dotenv
    load_dotenv(".env")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    import truststore
    truststore.inject_into_ssl()          # certificados do Windows, exigidos pelo WebSocket do Gemini
    client, connect = make_client(cfg)
    if client is None:
        print("Chave do Gemini ausente. Crie o arquivo .env com GEMINI_API_KEY.", file=sys.stderr)
        return 1
    from server import serve
    from viv.audio import AudioError
    from viv.wake import Hotkey
    parts = build(cfg, connect, client=client)
    try:
        parts.audio.start()
    except AudioError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Viv pronta. Microfone: {parts.audio.input_name}")
    print(f"HUD: http://127.0.0.1:{cfg['server']['port']}   Atalho: {cfg['wake']['hotkey']}   (Ctrl+C para sair)")
    if not parts.speaker.enrolled:
        print("Sem cadastro de voz: ações perigosas só são confirmadas pelo clique na HUD. "
              "Para cadastrar: .venv\\Scripts\\python.exe scripts\\enroll_voice.py")
    threading.Thread(target=parts.watcher.prepare, daemon=True, name="viv-whisper").start()
    threading.Thread(target=parts.speaker.warm, daemon=True, name="viv-voz").start()
    hotkey = Hotkey(cfg["wake"]["hotkey"], lambda: toggle(parts.viv))
    hotkey.start()
    parts.reminders.start()
    parts.routine.start()
    parts.relations.start()
    if parts.gowa.start():
        print("WhatsApp direto: iniciando o serviço local.")
    if briefing and parts.settings.get("inicio.boas_vindas"):
        threading.Thread(target=welcome, args=(parts,), daemon=True, name="viv-boas-vindas").start()

    def voice():
        try:
            asyncio.run(parts.viv.run())
        except Exception as exc:
            from viv.errors import ERRORS
            ERRORS.record("laço de voz", f"{type(exc).__name__}: {exc}")
            print(f"A conversa parou por um erro: {exc}", file=sys.stderr)
            BUS.emit("card", "A conversa parou por um erro", kind="data", body=str(exc)[:200], ok=False)
    threading.Thread(target=voice, daemon=True, name="viv-voice").start()
    if show:
        threading.Timer(1.2, open_hud, args=(cfg,)).start()
    try:
        serve(parts.app, cfg)
    finally:
        hotkey.stop()
        parts.reminders.stop()
        parts.routine.stop()
        parts.relations.stop()
        parts.gowa.stop()
        parts.watch.stop()
        parts.audio.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Viv, assistente de voz")
    parser.add_argument("--demo", action="store_true", help="só a HUD com eventos de demonstração")
    parser.add_argument("--no-hud", action="store_true", help="não abrir a janela da HUD")
    parser.add_argument("--briefing", action="store_true", help="dar as boas-vindas com o resumo do dia (usado ao iniciar com o Windows)")
    args = parser.parse_args()
    cfg = load_config()
    try:
        if args.demo:
            run_demo(cfg, not args.no_hud)
            return 0
        return run_full(cfg, not args.no_hud, args.briefing)
    except KeyboardInterrupt:
        print("Viv encerrada.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
