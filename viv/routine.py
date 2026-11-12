"""Rotina diária: avisa em voz alta cada item na sua hora."""
import threading
from datetime import datetime, timedelta
from typing import Callable

WINDOW = timedelta(minutes=10)     # item cuja hora passou há mais que isso não é falado com atraso


class RoutineClock:
    def __init__(self, settings, notify: Callable[[str], None], now: Callable[[], datetime] = datetime.now):
        self.settings, self.notify, self.now = settings, notify, now
        self._fired: dict[str, str] = {}     # id -> data em que já avisou
        self._stop = threading.Event()

    def due(self) -> list[dict]:
        now = self.now()
        today = now.date().isoformat()
        items = []
        for item in self.settings.routine_for(now.weekday()):
            hour, minute = (int(x) for x in item["hora"].split(":"))
            at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if at <= now < at + WINDOW and self._fired.get(item["id"]) != today:
                items.append(item)
        return items

    def tick(self) -> int:
        today, count = self.now().date().isoformat(), 0
        for item in self.due():
            try:
                self.notify(f"Item da rotina do usuário, agora às {item['hora']}: {item['texto']}. Avise o usuário.")
            except Exception:
                continue
            self._fired[item["id"]] = today
            count += 1
        return count

    def start(self) -> None:
        def loop():
            while not self._stop.wait(20):
                self.tick()
        threading.Thread(target=loop, daemon=True, name="viv-rotina").start()

    def stop(self) -> None:
        self._stop.set()
