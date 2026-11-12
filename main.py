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
    from viv.reminders import Reminders
    from viv.safety import Gate
    from viv.speaker import Speaker
    from viv.tools.registry import Context
    from viv.wake import WakeWatcher
    if audio is None:
        from viv.audio import AudioIO
        audio = AudioIO(cfg)
    memory = Memory(cfg["memory"]["path"])
    speaker = Speaker(cfg)
    ctx = Context(cfg, memory=memory, client=client)
    gate = Gate(cfg, ctx, speaker, Audit(cfg), notify=lambda text: None)
    watcher = WakeWatcher(cfg, audio, on_wake=lambda reason: viv.wake(reason))
    viv = Viv(cfg, audio, gate, memory, watcher, connect, gaps=CapabilityGaps())
    gate.notify = viv.notify
    reminders = Reminders(cfg["reminders"]["path"], viv.remind)
    ctx.reminders = reminders
    return Parts(viv, gate, memory, reminders, audio, speaker, watcher, create_app(viv, gate, audio, cfg, speaker))


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


def run_full(cfg: dict, show: bool) -> int:
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
    hotkey = Hotkey(cfg["wake"]["hotkey"], lambda: toggle(parts.viv))
    hotkey.start()
    parts.reminders.start()

    def voice():
        try:
            asyncio.run(parts.viv.run())
        except Exception as exc:
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
        parts.audio.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Viv, assistente de voz")
    parser.add_argument("--demo", action="store_true", help="só a HUD com eventos de demonstração")
    parser.add_argument("--no-hud", action="store_true", help="não abrir a janela da HUD")
    args = parser.parse_args()
    cfg = load_config()
    try:
        if args.demo:
            run_demo(cfg, not args.no_hud)
            return 0
        return run_full(cfg, not args.no_hud)
    except KeyboardInterrupt:
        print("Viv encerrada.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
