"""Portão das ações perigosas.

Ações comuns rodam direto. Ações perigosas ficam pendentes até o usuário confirmar
por voz (afirmação na transcrição + voz reconhecida) ou por clique na HUD. A decisão
é tomada aqui, a partir da fala e do áudio do usuário; o modelo não tem como confirmar.
"""
import re
import threading
import time
import unicodedata
from typing import Callable

from viv.bus import BUS
from viv.tools import registry

YES = {"sim", "confirmo", "confirma", "confirmado", "pode", "isso"}
NO = {"nao", "cancela", "cancelar", "cancele", "deixa", "pare"}


def _words(text: str) -> set[str]:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return set(re.findall(r"[a-z]+", text))


class Gate:
    def __init__(self, cfg: dict, ctx: registry.Context, speaker, audit,
                 notify: Callable[[str], None], clock: Callable[[], float] = time.monotonic):
        self.cfg, self.ctx, self.speaker, self.audit = cfg, ctx, speaker, audit
        self.notify, self.clock = notify, clock
        self.timeout = float(cfg.get("safety", {}).get("confirm_timeout_seconds", 30))
        self.pending: dict | None = None
        self._lock = threading.RLock()

    def submit(self, name: str, args: dict | None) -> str:
        if not registry.is_dangerous(name, self.cfg):
            return registry.call(name, args, self.ctx)
        try:
            text = registry.confirm_text(name, args)      # valida o pedido antes de incomodar o usuário
        except Exception as exc:
            return f"erro: {exc}"
        voice = bool(getattr(self.speaker, "enrolled", False))
        with self._lock:
            if self.pending is not None:
                self.audit.record("tool_blocked", tool=name, reason="outra ação pendente")
                return "recusado: já existe uma ação aguardando confirmação"
            self.pending = {"name": name, "args": args or {}, "text": text, "voice": voice,
                            "expires": self.clock() + self.timeout}
        self.audit.record("confirmation_requested", tool=name)
        BUS.emit("confirm", text, name=name, args=args or {}, seconds=int(self.timeout), voice=voice)
        if not voice:
            return "pendente: peça ao usuário que confirme clicando em Sim na tela (não há cadastro de voz)"
        return "pendente: peça ao usuário que confirme por voz ou na tela"

    def on_user_utterance(self, text: str, audio) -> None:
        with self._lock:
            if self.pending is None:
                return
            words = _words(text)
            if words & NO:
                return self._resolve(False, "voz")
            if not words & YES:
                return
            if self.speaker.is_owner(audio):
                return self._resolve(True, "voz")
        enrolled = bool(getattr(self.speaker, "enrolled", False))
        self.audit.record("confirmation_rejected", reason="voz não reconhecida" if enrolled else "sem cadastro de voz")
        BUS.emit("confirm_hint", "Voz não reconhecida. Clique em Sim para confirmar." if enrolled
                 else "Sem cadastro de voz. Clique em Sim para confirmar.")

    def on_click(self, accepted: bool) -> None:
        with self._lock:
            if self.pending is not None:
                self._resolve(bool(accepted), "clique")

    def tick(self) -> None:
        with self._lock:
            if self.pending is not None and self.clock() >= self.pending["expires"]:
                self._resolve(False, "tempo esgotado")

    def _resolve(self, accepted: bool, how: str) -> None:
        action, self.pending = self.pending, None
        self.audit.record("confirmation_result", tool=action["name"], accepted=accepted, how=how)
        if accepted:
            result = registry.call(action["name"], action["args"], self.ctx)
            self.audit.record("tool_executed", tool=action["name"])
            message = f"Ação confirmada pelo usuário ({how}). Resultado: {result}"
        else:
            message = f"Ação cancelada ({how}). Nada foi executado."
        BUS.emit("confirm_done", ok=accepted)
        self.notify(message)
