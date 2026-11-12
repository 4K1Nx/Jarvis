"""Registro de erros da Viv, para consulta posterior ("quais erros você teve?").

Guarda a origem e a mensagem do erro. Não guarda argumentos de ferramentas, falas
nem conteúdo de arquivos.
"""
import json
import threading
import time
from datetime import datetime
from pathlib import Path

MAX_LINES = 500


class ErrorLog:
    def __init__(self, path: str = "data/viv_erros.jsonl"):
        self.path = Path(path)
        self._lock = threading.Lock()

    def record(self, source: str, message: str) -> None:
        entry = {"ts": time.time(), "quando": datetime.now().isoformat(timespec="seconds"),
                 "origem": str(source)[:80], "erro": " ".join(str(message).split())[:500]}
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                lines = self.path.read_text(encoding="utf-8").splitlines()[-(MAX_LINES - 1):] if self.path.exists() else []
                lines.append(json.dumps(entry, ensure_ascii=False))
                self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass                      # registrar erro nunca pode derrubar a Viv

    def recent(self, limit: int = 20, hours: float | None = None) -> list[dict]:
        try:
            with self._lock:
                lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        entries = []
        for line in lines:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
        if hours is not None:
            cutoff = time.time() - hours * 3600
            entries = [e for e in entries if e.get("ts", 0) >= cutoff]
        return entries[-max(1, int(limit)):]

    def clear(self) -> int:
        count = len(self.recent(MAX_LINES))
        try:
            with self._lock:
                self.path.unlink(missing_ok=True)
        except OSError:
            return 0
        return count


ERRORS = ErrorLog()
