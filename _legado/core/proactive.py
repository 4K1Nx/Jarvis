"""Proactive layer: reminders, timers, routines and the morning briefing.

Runs on a CPU thread. Anything due is pushed straight into the TTS queue, so
Jarvis can speak first instead of only reacting.
"""
import json, os, threading, time, math
from dataclasses import dataclass, asdict
from typing import Callable, List

from core.bus import BUS

# Legacy demo messages are now passive Portuguese HUD tips, not user reminders.
LEGACY_DEMO_TEXTS = frozenset({
    "Morning. Say 'jarvis, brief me' whenever you're ready for the day's rundown.",
    "It's half eleven — want me to shut the machine down?",
})


def is_demo_tip(job):
    return job.repeat_daily and job.text in LEGACY_DEMO_TEXTS and not job.tool and not job.args



@dataclass
class Job:
    at: float
    text: str
    repeat_daily: bool = False
    tool: str | None = None
    args: dict | None = None


class Proactive:
    def __init__(self, cfg: dict, speak: Callable[[str], None], run_tool: Callable | None = None):
        self.cfg = cfg.get("proactive", {})
        self.path = self.cfg.get("jobs_path", "data/jobs.json")
        self.speak = speak
        self.run_tool = run_tool
        self._lock = threading.RLock()
        self.jobs: List[Job] = self._load()
        self._stop = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    # --- persistence ---
    def _load(self) -> List[Job]:
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as stream:
                return [Job(**j) for j in json.load(stream)]
        return []

    def _save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as stream:
            json.dump([asdict(j) for j in self.jobs], stream, indent=2, ensure_ascii=False)

    # --- api ---
    def schedule_in(self, seconds: float, text: str, tool=None, args=None):
        if not math.isfinite(seconds) or not 0 < seconds <= 366*86400 or not text.strip():
            raise ValueError('Prazo ou texto do lembrete inválido')
        with self._lock:
            self.jobs.append(Job(time.time() + seconds, text, False, tool, args))
            self._save()
        BUS.emit("proactive", f"scheduled +{int(seconds)}s · {text[:48]}")

    def schedule_daily(self, hhmm: str, text: str, tool=None, args=None):
        h, m = (int(x) for x in hhmm.split(":"))
        t = time.localtime()
        at = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, h, m, 0, 0, 0, -1))
        if at < time.time():
            at += 86400
        with self._lock:
            # Startup must not append another copy of the same daily routine.
            if any(j.repeat_daily and j.text == text and j.tool == tool and j.args == args
                   and time.strftime('%H:%M', time.localtime(j.at)) == hhmm for j in self.jobs):
                return
            self.jobs.append(Job(at, text, True, tool, args))
            self._save()
        BUS.emit("proactive", f"daily routine at {hhmm} · {text[:48]}")

    def pending(self):
        with self._lock:
            return sorted((j for j in self.jobs if not is_demo_tip(j)), key=lambda j: j.at)

    def cancel_all(self):
        with self._lock:
            self.jobs.clear(); self._save()

    # --- loop ---
    def run_due(self, now=None):
        now=time.time() if now is None else now
        with self._lock:
            for job in list(self.jobs):
                if is_demo_tip(job) or job.at > now:continue
                try:
                    if job.text:self.speak(job.text)
                    if job.tool and self.run_tool:self.run_tool(job.tool, job.args or {})
                except Exception:
                    BUS.emit('proactive', 'Falha ao entregar lembrete; permanece pendente.')
                    continue
                if job.repeat_daily:
                    while job.at <= now:job.at += 86400
                else:self.jobs.remove(job)
                self._save()
                BUS.emit('proactive', 'Lembrete entregue à sessão')

    def _loop(self):
        while not self._stop.is_set():
            self.run_due()
            self._stop.wait(1)
