"""Portão das ações perigosas.

Ações comuns rodam direto. Ações perigosas ficam pendentes até o usuário confirmar
por voz (afirmação na transcrição + voz reconhecida) ou por clique na HUD. A decisão
é tomada aqui, a partir da fala e do áudio do usuário; o modelo não tem como confirmar.

Ferramentas marcadas com `voice=True` (enviar o rascunho do WhatsApp que está na tela)
dispensam o cartão quando a voz do dono está na janela de confiança (viv/speaker.py) e a
última fala dele, há instantes, foi um pedido de envio (“envia”, “pode mandar”). O que
decide é a fala dele, nunca o modelo nem o conteúdo de uma mensagem recebida.
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
SEND = YES | {"envia", "envie", "enviar", "manda", "mande", "mandar", "responde", "responda", "responder", "ok", "beleza"}
SPOKEN_FOR = 60.0          # s em que a última fala do dono ainda vale como pedido


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
        self.mood = None                      # viv.mood.Mood, quando o humor está ligado
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

    def submit(self, name: str, args: dict | None) -> str:
        self.tick()                           # uma confirmação vencida não pode travar a próxima
        if self.mood is not None and self.mood.refuses(name):
            self.audit.record("tool_blocked", tool=name, reason="humor")
            return ("humor: você não está com vontade de fazer isso agora e nada foi executado. Diga isso em uma "
                    "frase, do seu jeito. Se o usuário insistir, chame a ferramenta de novo.")
        if not self._needs_confirmation(name):
            return registry.call(name, args, self.ctx)
        try:
            text = registry.confirm_text(name, args)      # valida o pedido antes de incomodar o usuário
        except Exception as exc:
            return f"erro: {exc}"
        if self._spoken_approval(name, args):
            self.said = (float("-inf"), set())           # um pedido falado autoriza uma ação só
            self.audit.record("tool_executed", tool=name, how="voz reconhecida")
            BUS.emit("card", text, kind="action", body="Autorizado pela sua voz.", ok=True)
            return registry.call(name, args, self.ctx)
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
        if accepted:
            result = registry.call(action["name"], action["args"], self.ctx)
            self.audit.record("tool_executed", tool=action["name"])
            message = f"Ação confirmada pelo usuário ({how}). Resultado: {result}"
        else:
            message = f"Ação cancelada ({how}). Nada foi executado."
        BUS.emit("confirm_done", ok=accepted)
        self.notify(message)
