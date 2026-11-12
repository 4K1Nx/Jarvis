"""Memória simples da Viv: fatos sobre o usuário e os últimos turnos da conversa."""
import json
import threading
import unicodedata
from pathlib import Path

MAX_TURNS = 100


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


class Memory:
    def __init__(self, path: str):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._facts: list[str] = []
        self._turns: list[dict] = []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._facts = [str(f) for f in data.get("facts", [])]
            self._turns = [t for t in data.get("turns", []) if isinstance(t, dict) and "text" in t][-MAX_TURNS:]
        except (OSError, ValueError, AttributeError):
            pass  # arquivo ausente ou corrompido: começa vazia

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"facts": self._facts, "turns": self._turns}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(self.path)

    def remember(self, fact: str) -> str:
        fact = fact.strip()
        if not fact:
            return "nada para lembrar"
        with self._lock:
            if fact not in self._facts:
                self._facts.append(fact)
                self._save()
        return "anotado"

    def forget(self, fragment: str) -> str:
        key = _fold(fragment.strip())
        if not key:
            return "nada para esquecer"
        with self._lock:
            kept = [f for f in self._facts if key not in _fold(f)]
            removed = len(self._facts) - len(kept)
            if removed:
                self._facts = kept
                self._save()
        return f"{removed} fato(s) esquecido(s)"

    def facts(self) -> list[str]:
        with self._lock:
            return list(self._facts)

    def add_turn(self, role: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        with self._lock:
            self._turns = (self._turns + [{"role": role, "text": text}])[-MAX_TURNS:]
            self._save()

    def recent_turns(self, n: int) -> list[dict]:
        with self._lock:
            return list(self._turns[-n:]) if n > 0 else []

    def prompt_block(self, n: int) -> str:
        lines = []
        facts = self.facts()
        if facts:
            lines.append("O que você sabe sobre o usuário:")
            lines += [f"- {f}" for f in facts]
        turns = self.recent_turns(n)
        if turns:
            lines.append("Trecho final da conversa anterior:")
            lines += [f"{'Usuário' if t.get('role') == 'user' else 'Viv'}: {t['text']}" for t in turns]
        return "\n".join(lines)
