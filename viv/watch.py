"""Vigia da tela: olha a tela de tempos em tempos e avisa quando uma condição acontecer
(um download terminar, uma instalação acabar, um erro aparecer)."""
import threading
import time
from typing import Callable

from viv.bus import BUS

QUESTION = ("Você está vigiando a tela para o usuário. Condição a observar: {condition}. "
            "Na primeira linha responda apenas SIM se a condição já aconteceu, ou NAO se ainda não. "
            "Na segunda linha descreva em uma frase curta o estado atual (por exemplo, o progresso).")
MAX_FAILURES = 5


class ScreenWatch:
    def __init__(self, look: Callable[[str], str], notify: Callable[[str], None],
                 clock: Callable[[], float] = time.monotonic):
        self.look, self.notify, self.clock = look, notify, clock
        self.active: dict | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()

    def start(self, condition: str, interval_seconds: float = 60, limit_minutes: float = 180) -> str:
        condition = condition.strip()
        if not condition:
            raise ValueError("diga o que devo observar")
        with self._lock:
            replaced = self.active is not None
            self.active = {"condition": condition, "interval": max(20.0, float(interval_seconds)),
                           "deadline": self.clock() + max(1.0, float(limit_minutes)) * 60,
                           "last": "", "failures": 0, "checks": 0, "token": object()}
            token = self.active["token"]
        self._wake.set()
        threading.Thread(target=self._loop, args=(token,), daemon=True, name="viv-vigia").start()
        return ("vigia anterior substituída; " if replaced else "") + f"vigiando a tela: {condition}"

    def stop(self) -> str:
        with self._lock:
            was, self.active = self.active, None
        self._wake.set()
        return "vigia encerrada" if was else "não havia vigia ativa"

    def status(self) -> str:
        with self._lock:
            a = self.active
            if a is None:
                return "nenhuma vigia ativa"
            return f"vigiando: {a['condition']}. {a['checks']} verificação(ões). Último estado: {a['last'] or 'ainda sem leitura'}"

    def _loop(self, token) -> None:
        while True:
            with self._lock:
                if self.active is None or self.active["token"] is not token:
                    return
                interval = self.active["interval"]
            if self.tick(token):
                return
            self._wake.clear()
            self._wake.wait(interval)

    def tick(self, token=None) -> bool:
        """Uma verificação. Devolve True quando a vigia terminou."""
        with self._lock:
            a = self.active
            if a is None or (token is not None and a["token"] is not token):
                return True
        if self.clock() >= a["deadline"]:
            return self._finish(a, f"A vigia da tela chegou ao tempo limite sem a condição acontecer: {a['condition']}. "
                                   f"Último estado: {a['last'] or 'desconhecido'}.", ok=False)
        try:
            answer = self.look(QUESTION.format(condition=a["condition"])).strip()
        except Exception as exc:
            a["failures"] += 1
            if a["failures"] >= MAX_FAILURES:
                return self._finish(a, f"Parei de vigiar a tela porque não consegui analisá-la ({exc}).", ok=False)
            return False
        a["failures"], a["checks"] = 0, a["checks"] + 1
        lines = [line.strip() for line in answer.splitlines() if line.strip()]
        first = lines[0].upper() if lines else ""
        a["last"] = lines[1] if len(lines) > 1 else (lines[0] if lines else "")
        if first.startswith("SIM"):
            return self._finish(a, f"A condição que você vigiava na tela aconteceu: {a['condition']}. "
                                   f"Estado: {a['last']}. Avise o usuário.", ok=True)
        return False

    def _finish(self, a: dict, message: str, ok: bool) -> bool:
        with self._lock:
            if self.active is a:
                self.active = None
        BUS.emit("card", "Vigia da tela", kind="data", body=a["last"] or a["condition"], ok=ok)
        self.notify(message)
        return True
