"""Ações agendadas: a Viv executa uma ferramenta num horário marcado (mandar uma mensagem, abrir um
programa, desligar o PC), uma vez ou todo dia.

O usuário confirma a ação na hora de agendar, vendo exatamente o que será feito e quando; no horário ela
roda sem perguntar de novo. A Viv precisa estar aberta: uma ação que perdeu a hora por mais de LATE segundos
(a Viv estava fechada, o PC desligado) não é executada atrasada, só avisada.
"""
import json
import threading
import time
from pathlib import Path
from typing import Callable

LATE = 15 * 60
DAY = 86400
MAX_JOBS = 50


class Schedule:
    def __init__(self, path: str, run: Callable[[str, dict], str], report: Callable[[dict, str, str], None],
                 clock: Callable[[], float] = time.time):
        self.path, self.run, self.report, self.clock = Path(path), run, report, clock
        self._lock = threading.RLock()
        self._stop = threading.Event()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._jobs = [j for j in data if isinstance(j, dict) and j.get("tool") and isinstance(j.get("at"), (int, float))]
        except (OSError, ValueError, TypeError):
            self._jobs = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._jobs, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, at: float, tool: str, args: dict, text: str, daily: bool = False) -> dict:
        with self._lock:
            if len(self._jobs) >= MAX_JOBS:
                raise ValueError("há ações agendadas demais; cancele alguma antes")
            job = {"at": float(at), "tool": tool, "args": dict(args or {}), "text": str(text).strip()[:300], "daily": bool(daily)}
            self._jobs.append(job)
            self._save()
        return dict(job)

    def pending(self) -> list[dict]:
        with self._lock:
            return sorted((dict(j) for j in self._jobs), key=lambda j: j["at"])

    def cancel(self, number: int) -> dict | None:
        """Cancela pela posição na lista de `pending` (a partir de 1)."""
        with self._lock:
            ordered = sorted(self._jobs, key=lambda j: j["at"])
            if not 1 <= number <= len(ordered):
                return None
            job = ordered[number - 1]
            self._jobs.remove(job)
            self._save()
        return dict(job)

    def run_due(self) -> int:
        now = self.clock()
        with self._lock:
            due = [j for j in self._jobs if j["at"] <= now]
            for job in due:                    # sai da lista antes de rodar: uma queda no meio não repete o envio
                self._jobs.remove(job)
                if job.get("daily"):
                    self._jobs.append({**job, "at": job["at"] + DAY * (int((now - job["at"]) // DAY) + 1)})
            if due:
                self._save()
        for job in due:
            if now - job["at"] > LATE:
                self.report(job, "", "perdida")
                continue
            try:
                result = str(self.run(job["tool"], job["args"]))
            except Exception as exc:
                result = f"erro: {exc}"
            self.report(job, result, "falhou" if result.startswith("erro") else "feita")
        return len(due)

    def start(self) -> None:
        def loop():
            while not self._stop.wait(1):
                try:
                    self.run_due()
                except Exception:
                    pass                      # um agendamento com problema não derruba os outros
        threading.Thread(target=loop, daemon=True, name="viv-agenda").start()

    def stop(self) -> None:
        self._stop.set()
