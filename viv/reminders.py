"""Lembretes com prazo. Entradas antigas do arquivo (rotinas diárias, tarefas com
ferramenta) são preservadas no disco, mas não são listadas nem disparadas."""
import json
import math
import threading
import time
from pathlib import Path
from typing import Callable


def _is_reminder(job: dict) -> bool:
    return (isinstance(job, dict) and not job.get("repeat_daily") and not job.get("tool")
            and isinstance(job.get("at"), (int, float)) and bool(job.get("text")))


class Reminders:
    def __init__(self, path: str, notify: Callable[[str], None]):
        self.path = Path(path)
        self.notify = notify
        self.deliver: Callable[[str, str], None] | None = None   # (jid, texto): lembrete pedido pelo WhatsApp
        self._lock = threading.RLock()
        self._stop = threading.Event()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._jobs = data if isinstance(data, list) else []
        except (OSError, ValueError):
            self._jobs = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._jobs, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def schedule_in(self, seconds: float, text: str, to: str = "") -> str:
        seconds = float(seconds)
        if not math.isfinite(seconds) or not 0 < seconds <= 366 * 86400 or not text.strip():
            raise ValueError("prazo ou texto do lembrete inválido")
        with self._lock:
            job = {"at": time.time() + seconds, "text": text.strip(), "repeat_daily": False, "tool": None, "args": None}
            if to:
                job["para"] = to
            self._jobs.append(job)
            self._save()
        return "lembrete criado"

    def pending(self) -> list[dict]:
        with self._lock:
            return sorted((dict(j) for j in self._jobs if _is_reminder(j)), key=lambda j: j["at"])

    def run_due(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        delivered = 0
        with self._lock:
            for job in [j for j in self._jobs if _is_reminder(j) and j["at"] <= now]:
                try:
                    if job.get("para") and self.deliver is not None:
                        self.deliver(job["para"], job["text"])
                    else:
                        self.notify(job["text"])
                except Exception:
                    continue  # continua pendente e tenta de novo no próximo ciclo
                self._jobs.remove(job)
                self._save()
                delivered += 1
        return delivered

    def start(self) -> None:
        def loop():
            while not self._stop.wait(1):
                self.run_due()
        threading.Thread(target=loop, daemon=True, name="viv-reminders").start()

    def stop(self) -> None:
        self._stop.set()
