"""As pessoas da vida do usuário, do jeito que a Viv as conhece.

Cada contato (o nome salvo no WhatsApp) pode ganhar um apelido escolhido pela Viv ou
pelo usuário, a relação com o usuário e anotações. Ela fala das pessoas pelo apelido
ou pela relação; o nome real só é usado para achar a conversa certa e no cartão de
confirmação de envio.
"""
import json
import threading
import unicodedata
from pathlib import Path


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text).casefold())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


class People:
    def __init__(self, path: str = "data/viv_pessoas.json"):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._items: dict[str, dict] = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._items = {k: v for k, v in data.items() if isinstance(v, dict) and v.get("contato")}
        except (OSError, ValueError, AttributeError):
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._items, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def define(self, contato: str, apelido: str = "", relacao: str = "", notas: str = "") -> dict:
        """Cria ou atualiza uma pessoa. Campos vazios mantêm o que já havia."""
        contato = " ".join(str(contato).split())
        if not contato:
            raise ValueError("informe o nome do contato como está salvo")
        with self._lock:
            key = _fold(contato)
            item = self._items.get(key, {"contato": contato, "apelido": "", "relacao": "", "notas": ""})
            for field, value in (("apelido", apelido), ("relacao", relacao), ("notas", notas)):
                if str(value or "").strip():
                    item[field] = str(value).strip()[:200]
            self._items[key] = item
            self._save()
            return dict(item)

    def style(self, contato: str, tom: str = "", exemplo: str = "") -> dict:
        """Como o usuário escreve para esta pessoa: o tom pedido e até cinco mensagens dele como exemplo."""
        item = self.define(contato)
        with self._lock:
            stored = self._items[_fold(item["contato"])]
            if str(tom or "").strip():
                stored["tom"] = str(tom).strip()[:200]
            if str(exemplo or "").strip():
                stored["exemplos"] = (stored.get("exemplos", []) + [str(exemplo).strip()[:400]])[-5:]
            self._save()
            return dict(stored)

    def find(self, ref: str) -> dict | None:
        """Acha a pessoa pelo apelido, pela relação ou pelo nome do contato."""
        key = _fold(ref)
        if not key:
            return None
        with self._lock:
            items = list(self._items.values())
        for exact in (True, False):
            for item in items:
                names = [_fold(item[f]) for f in ("apelido", "relacao", "contato") if item.get(f)]
                if any(key == n if exact else (key in n or n in key) for n in names):
                    return dict(item)
        return None

    def get(self, contato: str) -> dict | None:
        """A pessoa salva com exatamente este nome de contato (sem aproximação)."""
        with self._lock:
            item = self._items.get(_fold(contato))
            return dict(item) if item else None

    def resolve(self, ref: str) -> str:
        """Nome real do contato para um apelido ou relação; sem cadastro, devolve o próprio texto."""
        item = self.find(ref)
        return item["contato"] if item else " ".join(str(ref).split())

    def label(self, contato: str) -> str:
        """Como a Viv chama este contato: apelido, senão a relação, senão o nome salvo."""
        item = self._items.get(_fold(contato))
        return (item.get("apelido") or item.get("relacao") or contato) if item else contato

    def forget(self, ref: str) -> bool:
        item = self.find(ref)
        if item is None:
            return False
        with self._lock:
            self._items.pop(_fold(item["contato"]), None)
            self._save()
        return True

    def all(self) -> list[dict]:
        with self._lock:
            return [dict(item) for item in self._items.values()]

    def prompt_block(self) -> str:
        people = self.all()
        if not people:
            return ""
        lines = ["Pessoas que você conhece (chame-as pelo apelido ou pela relação, não pelo nome do contato):"]
        for p in people:
            extra = "; ".join(x for x in (p.get("relacao"), p.get("notas")) if x)
            lines.append(f"- {p.get('apelido') or p['contato']}: contato “{p['contato']}”" + (f"; {extra}" if extra else ""))
        return "\n".join(lines)
