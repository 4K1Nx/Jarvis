"""Consume microphone frames only while synchronous TTS playback blocks the turn loop."""
import queue
import threading
from core.bus import BUS


class BargeIn:
    def __init__(self, audio, interrupt):
        self.audio = audio
        self.interrupt = interrupt
        self.done = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.done.clear()
        self.thread = threading.Thread(target=self._listen, daemon=True, name='viv-barge-in')
        self.thread.start()

    def finish(self):
        self.done.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join()

    def _listen(self):
        voiced = 0
        needed = max(1, 240 // self.audio.frame_ms)
        while not self.done.is_set():
            try:
                frame = self.audio.q.get(timeout=.05)
            except queue.Empty:
                continue
            # Keep onset frames for the next utterance instead of dropping them.
            self.audio._pre_roll.append(frame)
            BUS.emit('level', '', value=self.audio.level(frame), source='microphone')
            voiced = voiced + 1 if self.audio.is_voice(frame) else 0
            if voiced >= needed:
                self.audio._speech_run = voiced
                self.interrupt()
                return
