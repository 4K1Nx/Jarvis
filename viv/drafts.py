"""Rascunho de mensagem: toda mensagem começa aqui e só sai depois de aprovada.

Fica só na memória do programa — o texto de uma conversa pessoal não vai para arquivo
nem para registro. A aprovação vale para um destinatário e um texto exatos: mudar
qualquer um dos dois cria outro rascunho e exige nova confirmação. O estado do envio
é guardado para que uma falha de resultado incerto nunca vire mensagem duplicada.
"""
import threading
import time
import unicodedata


def _key(contact: str, text: str) -> tuple[str, str]:
    fold = unicodedata.normalize("NFKD", str(contact).casefold())
    fold = " ".join("".join(c for c in fold if not unicodedata.combining(c)).split())
    return fold, " ".join(str(text).split())


class Drafts:
    def __init__(self):
        self._lock = threading.Lock()
        self.current: dict | None = None     # {"contato", "texto", "estado"}

    def write(self, contact: str, text: str) -> dict:
        """Cria ou edita o rascunho. Um rascunho editado volta ao estado inicial."""
        contact, text = " ".join(str(contact).split()), str(text).strip()
        if not contact or not text:
            raise ValueError("o rascunho precisa de destinatário e texto")
        with self._lock:
            same = self.current is not None and _key(self.current["contato"], self.current["texto"]) == _key(contact, text)
            if not same:
                self.current = {"contato": contact, "texto": text, "estado": "rascunho", "at": time.monotonic()}
            return dict(self.current)

    def match(self, contact: str, text: str) -> dict | None:
        """O rascunho mostrado ao usuário, se for exatamente este destinatário e este texto."""
        with self._lock:
            if self.current is not None and _key(self.current["contato"], self.current["texto"]) == _key(contact, text):
                return self.current
            return None

    def shown_at(self, contact: str, text: str) -> float | None:
        """Quando este rascunho apareceu na tela (relógio monotônico), ou None se não é o atual."""
        draft = self.match(contact, text)
        return None if draft is None else draft.get("at")

    def mark(self, contact: str, text: str, state: str) -> None:
        draft = self.match(contact, text)
        if draft is not None:
            draft["estado"] = state

    def cancel(self) -> bool:
        with self._lock:
            had, self.current = self.current is not None, None
            return had


DRAFTS = Drafts()
