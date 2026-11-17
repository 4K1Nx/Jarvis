"""Portão das ações perigosas.

Ações comuns rodam direto. Ações perigosas ficam pendentes até o usuário confirmar
por voz (afirmação na transcrição + voz reconhecida) ou por clique na HUD. A decisão
é tomada aqui, a partir da fala e do áudio do usuário; o modelo não tem como confirmar.

Ferramentas marcadas com `voice=True` (enviar o rascunho do WhatsApp que está na tela)
dispensam o cartão quando a voz do dono está na janela de confiança (viv/speaker.py) e a
última fala dele, há instantes, foi um pedido de envio (“envia”, “pode mandar”). O que
decide é a fala dele, nunca o modelo nem o conteúdo de uma mensagem recebida.
"""
import json
import re
import threading
import time
import unicodedata
from typing import Callable

from viv.bus import BUS
from viv.tools import registry

YES = {"sim", "confirmo", "confirma", "confirmado", "pode", "isso"}
NO = {"nao", "cancela", "cancelar", "cancele", "deixa", "pare"}
SEND = YES | {"envia", "envie", "enviar", "manda", "mande", "mandar", "responde", "responda", "responder", "ok", "beleza"}
SPOKEN_FOR = 60.0          # s em que a última fala do dono ainda vale como pedido
QUEUE = 3                  # confirmações que podem esperar a vez atrás da que está na tela
REPEAT = 20.0             # s: o modelo repetir o pedido recém-confirmado não abre outro cartão


def _key(name: str, args: dict | None) -> tuple[str, str]:
    return name, json.dumps(args or {}, sort_keys=True, ensure_ascii=False, default=str)


def _words(text: str) -> set[str]:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return set(re.findall(r"[a-z]+", text))


class Gate:
    def __init__(self, cfg: dict, ctx: registry.Context, speaker, audit,
                 notify: Callable[[str], None], clock: Callable[[], float] = time.monotonic,
                 spawn: Callable[[Callable[[], None]], None] | None = None):
        self.cfg, self.ctx, self.speaker, self.audit = cfg, ctx, speaker, audit
        self.notify, self.clock = notify, clock
        # a ação confirmada roda fora da fala e da trava: o cartão fecha na hora e a conversa não congela
        self.spawn = spawn or (lambda job: threading.Thread(target=job, daemon=True, name="viv-acao-confirmada").start())
        self.last: dict | None = None         # última ação confirmada: chave, quando e resultado (None = rodando)
        self.timeout = float(cfg.get("safety", {}).get("confirm_timeout_seconds", 30))
        self.pending: dict | None = None
        self.waiting: list[dict] = []         # confirmações pedidas enquanto outra estava na tela
        self.mood = None                      # viv.mood.Mood, quando o humor está ligado
        self.tasks = None                     # viv.tasks.Tasks: o que demora segue em segundo plano
        self.said: tuple[float, set[str]] = (float("-inf"), set())   # última fala do usuário
        self._lock = threading.RLock()

    def _needs_confirmation(self, name: str) -> bool:
        if registry.is_dangerous(name, self.cfg):
            return True
        # conteúdo pessoal (WhatsApp, e-mail) pedido por uma voz que não é a do dono
        stranger = getattr(self.speaker, "stranger_present", None)
        return registry.is_private(name) and stranger is not None and stranger()

    def _spoken_approval(self, name: str, args: dict | None) -> bool:
        """O dono, com a voz reconhecida há pouco, acabou de pedir esta ação com as próprias palavras,
        depois de vê-la na tela?"""
        rule = registry.voice_approvable(name)
        trusted = getattr(self.speaker, "trusted", None)
        when, words = self.said
        if not rule or trusted is None or not trusted():
            return False
        if self.clock() - when > SPOKEN_FOR or not words & SEND or words & NO:
            return False
        if callable(rule):
            try:
                shown = rule(args or {})
            except Exception:
                return False
            return shown is not None and when > shown       # “envia” dito antes do rascunho não vale para ele
        return True

    def _call(self, name: str, args: dict | None) -> str:
        """Executa uma ação já autorizada. Com as tarefas ligadas, o que demora não segura a conversa."""
        if self.tasks is None:
            return registry.call(name, args, self.ctx)
        return self.tasks.run(name, args, lambda: registry.call(name, args, self.ctx),
                              title=registry.describe(name, args), group=registry.module_of(name))

    def submit(self, name: str, args: dict | None) -> str:
        self.tick()                           # uma confirmação vencida não pode travar a próxima
        if self.mood is not None and self.mood.refuses(name):
            self.audit.record("tool_blocked", tool=name, reason="humor")
            return ("humor: você não está com vontade de fazer isso agora e nada foi executado. Diga isso em uma "
                    "frase, do seu jeito. Se o usuário insistir, chame a ferramenta de novo.")
        if not self._needs_confirmation(name):
            return self._call(name, args)
        try:
            text = registry.confirm_text(name, args)      # valida o pedido antes de incomodar o usuário
        except Exception as exc:
            return f"erro: {exc}"
        repeated = self._repeated(_key(name, args))
        if repeated:
            return repeated
        if self._spoken_approval(name, args):
            self.said = (float("-inf"), set())           # um pedido falado autoriza uma ação só
            self.audit.record("tool_executed", tool=name, how="voz reconhecida")
            BUS.emit("card", text, kind="action", body="Autorizado pela sua voz.", ok=True)
            return self._call(name, args)
        voice = bool(getattr(self.speaker, "enrolled", False))
        action = {"name": name, "args": args or {}, "text": text, "voice": voice, "key": _key(name, args)}
        with self._lock:
            if self.pending is not None:
                # outro cartão está na tela: este espera a vez, em vez de ser recusado e esquecido
                if len(self.waiting) >= QUEUE:
                    self.audit.record("tool_blocked", tool=name, reason="fila de confirmações cheia")
                    return "recusado: já há confirmações demais esperando; peça ao usuário que responda às que estão na tela"
                self.waiting.append(action)
                self.audit.record("confirmation_queued", tool=name)
                return ("pendente: há outra confirmação na tela; esta aparece em seguida. Diga ao usuário que são "
                        f"{len(self.waiting) + 1} confirmações, uma de cada vez, e não chame de novo")
            self._ask(action)
        if not voice:
            return "pendente: peça ao usuário que confirme clicando em Sim na tela (não há cadastro de voz)"
        return "pendente: peça ao usuário que confirme por voz ou na tela"

    def _ask(self, action: dict) -> None:
        """Põe uma confirmação na tela. O prazo dela começa agora, não quando entrou na fila."""
        self.pending = {**action, "expires": self.clock() + self.timeout}
        self.audit.record("confirmation_requested", tool=action["name"])
        BUS.emit("confirm", action["text"], name=action["name"], args=action["args"], seconds=int(self.timeout),
                 voice=action["voice"])

    def _repeated(self, key: tuple[str, str]) -> str:
        """O modelo também ouve o “sim” e às vezes chama a mesma ferramenta de novo. Isso não pode abrir um
        segundo cartão idêntico nem executar a ação duas vezes."""
        with self._lock:
            if any(item["key"] == key for item in self.waiting):
                return ("pendente: este mesmo pedido já está na fila de confirmações. Não chame de novo; o sistema "
                        "avisa quando o usuário confirmar ou cancelar")
            if self.pending is not None and self.pending["key"] == key:
                return ("pendente: este mesmo pedido já está na tela esperando a confirmação do usuário. Não chame de "
                        "novo; o sistema avisa quando ele confirmar ou cancelar")
            last = self.last
            if last is None or last["key"] != key or self.clock() - last["at"] > REPEAT:
                return ""
            if last["result"] is not None and last["result"].startswith("erro"):
                return ""                     # o que falhou pode ser tentado de novo, com nova confirmação
        if last["result"] is None:
            return ("o usuário já confirmou este mesmo pedido agora há pouco e ele está sendo executado. Não chame de "
                    "novo nem peça outra confirmação; o sistema avisa o resultado")
        return (f"o usuário já confirmou este mesmo pedido agora há pouco e ele já foi executado. Resultado: "
                f"{last['result']}. Não chame de novo")

    def on_user_utterance(self, text: str, audio) -> None:
        with self._lock:
            words = _words(text)
            if self.pending is None:
                self.said = (self.clock(), words)
                return
            self.said = (float("-inf"), set())       # resposta a uma confirmação não autoriza a próxima ação
            if words & NO:
                return self._resolve(False, "voz")
            if not words & YES:
                return
            if self.speaker.is_owner(audio):
                return self._resolve(True, "voz")
        enrolled = bool(getattr(self.speaker, "enrolled", False))
        self.audit.record("confirmation_rejected", reason="voz não reconhecida" if enrolled else "sem cadastro de voz",
                          score=round(float(getattr(self.speaker, "last_score", 0.0)), 3))
        BUS.emit("confirm_hint", "Não reconheci a sua voz. Diga “sim, pode fazer” ou clique em Sim." if enrolled
                 else "Sem cadastro de voz. Clique em Sim para confirmar.")
        # o modelo também ouviu o “sim”: sem este aviso ele diria que já está fazendo
        self.notify("O “sim” do usuário não confirmou a ação: " + ("a voz não foi reconhecida" if enrolled else
                    "não há cadastro de voz") + ". Ela ainda NÃO foi executada e o cartão continua na tela. Diga em uma "
                    "frase que ele precisa " + ("repetir “sim, pode fazer” ou " if enrolled else "") + "clicar em Sim.")

    def on_click(self, accepted: bool) -> None:
        with self._lock:
            if self.pending is not None:
                self._resolve(bool(accepted), "clique")

    def tick(self) -> None:
        with self._lock:
            if self.pending is not None and self.clock() >= self.pending["expires"]:
                self._resolve(False, "tempo esgotado")

    def remaining(self) -> int:
        """Segundos que faltam para a confirmação pendente vencer (0 sem pendência)."""
        with self._lock:
            return max(0, int(self.pending["expires"] - self.clock())) if self.pending else 0

    def _resolve(self, accepted: bool, how: str) -> None:
        action, self.pending = self.pending, None
        self.audit.record("confirmation_result", tool=action["name"], accepted=accepted, how=how)
        BUS.emit("confirm_done", ok=accepted)            # o cartão fecha já, antes de a ação terminar
        if self.waiting:
            self._ask(self.waiting.pop(0))               # a próxima da fila entra na tela
        if not accepted:
            if self.mood is not None and how != "tempo esgotado":
                self.mood.feel("cancelada")
            self.notify(f"Ação cancelada ({how}). Nada foi executado.")
            return
        entry = {"key": action["key"], "at": self.clock(), "result": None}
        self.last = entry

        def run():
            result = self._call(action["name"], action["args"])
            entry["result"] = str(result)[:400]
            self.audit.record("tool_executed", tool=action["name"])
            self.notify(f"Ação confirmada pelo usuário ({how}) e executada. Resultado: {result}. Conte o resultado em "
                        "uma frase; se você já disse que ia fazer, não repita a explicação.")
        self.spawn(run)
