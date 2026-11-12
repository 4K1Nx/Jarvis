"""Gatilhos de ativação usados enquanto a Viv dorme: duas palmas, o nome e o atalho."""
import re
import unicodedata
from collections import deque
from typing import Callable

import numpy as np

from viv.audio import rms

RATE, FRAME_SECONDS = 16000, 0.02


class ClapDetector:
    """Duas palmas: transientes curtos, fortes e de banda larga, separados por
    min_gap..max_gap. Fala não dispara porque tem poucos cruzamentos por zero."""

    def __init__(self, min_gap_ms: int = 120, max_gap_ms: int = 700):
        self.min_gap, self.max_gap = min_gap_ms / 1000, max_gap_ms / 1000
        self.reset()

    def reset(self) -> None:
        self._noise_floor, self._high, self._times = 0.003, False, []

    def feed(self, frame: bytes, now: float) -> bool:
        x = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        if len(x) < 2:
            return False
        level = float(np.sqrt(np.mean(x * x)))
        zcr = float(np.mean(x[:-1] * x[1:] < 0))
        high = level > max(0.018, self._noise_floor * 4.0) and zcr > 0.12
        rising, self._high = high and not self._high, high
        if rising:
            self._times = [t for t in self._times if now - t <= self.max_gap]
            if not self._times or now - self._times[-1] >= self.min_gap:
                self._times.append(now)
                if len(self._times) >= 2:
                    self._times.clear()
                    return True
        elif not high:
            self._noise_floor = self._noise_floor * 0.98 + min(level, 0.015) * 0.02
        return False


def matches_name(text: str, aliases: list[str]) -> bool:
    """O texto contém um dos apelidos como palavra inteira?"""
    def fold(s):
        s = unicodedata.normalize("NFKD", s.casefold())
        return "".join(c for c in s if not unicodedata.combining(c))
    words = set(re.findall(r"[a-z]+", fold(text)))
    return bool(words & {fold(a) for a in aliases})


class NameSpotter:
    """Recorta trechos curtos de fala por energia e pergunta ao transcritor se o nome foi dito."""
    START_FRAMES, END_FRAMES, MIN_VOICED, PRE_ROLL = 3, 15, 15, 5

    def __init__(self, aliases: list[str], transcribe: Callable[[np.ndarray], str], max_seconds: float = 3.0):
        self.aliases, self.transcribe = aliases, transcribe
        self.max_frames = int(max_seconds / FRAME_SECONDS)
        self.reset()

    def reset(self) -> None:
        self._floor = 0.003
        self._pre: deque = deque(maxlen=self.PRE_ROLL)
        self._segment: list[bytes] | None = None
        self._run = self._quiet = self._voiced = 0

    def feed(self, frame: bytes, now: float) -> bool:
        level = rms(frame)
        loud = level > max(0.012, self._floor * 3.0)
        if self._segment is None:
            self._pre.append(frame)
            self._run = self._run + 1 if loud else 0
            if not loud:
                self._floor = self._floor * 0.98 + min(level, 0.02) * 0.02
            if self._run >= self.START_FRAMES:
                self._segment, self._voiced, self._quiet = list(self._pre), self._run, 0
            return False
        self._segment.append(frame)
        self._voiced += loud
        self._quiet = 0 if loud else self._quiet + 1
        if self._quiet < self.END_FRAMES and len(self._segment) < self.max_frames:
            return False
        segment, voiced = self._segment, self._voiced
        self._segment, self._run = None, 0
        self._pre.clear()
        if voiced < self.MIN_VOICED:
            return False
        audio = np.frombuffer(b"".join(segment), dtype=np.int16).astype(np.float32) / 32768.0
        try:
            return matches_name(self.transcribe(audio), self.aliases)
        except Exception:
            return False


def whisper_transcriber(model_name: str = "tiny") -> Callable[[np.ndarray], str]:
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device="cpu", compute_type="int8")

    def transcribe(audio: np.ndarray) -> str:
        segments, _ = model.transcribe(audio, language="pt", beam_size=1, vad_filter=False,
                                       condition_on_previous_text=False, initial_prompt="Ei, Viv.")
        return " ".join(s.text for s in segments)
    return transcribe


class Hotkey:
    def __init__(self, combo: str, callback: Callable[[], None]):
        self.combo, self.callback, self._handle = combo, callback, None

    def start(self) -> None:
        try:
            import keyboard
            self._handle = keyboard.add_hotkey(self.combo, self.callback)
        except Exception as exc:
            print(f"Aviso: não foi possível registrar o atalho {self.combo}: {exc}")

    def stop(self) -> None:
        if self._handle is not None:
            import keyboard
            keyboard.remove_hotkey(self._handle)
            self._handle = None


class WakeWatcher:
    def __init__(self, cfg: dict, audio, on_wake: Callable[[str], None],
                 transcribe: Callable[[np.ndarray], str] | None = None):
        w = cfg.get("wake", {})
        self.audio, self.on_wake = audio, on_wake
        self._frames = 0   # o tempo vem do áudio, não do relógio: imune a atrasos de processamento
        self._model = w.get("whisper_model", "tiny")
        self._aliases = w.get("aliases", ["Viv"])
        self._transcribe = transcribe
        self.clap = ClapDetector(w.get("clap_min_gap_ms", 120), w.get("clap_max_gap_ms", 700))
        self.clap_on = bool(w.get("clap_enabled", True))
        self._name_enabled = bool(w.get("name_enabled", True))
        self.name_on = self._name_enabled
        self.name: NameSpotter | None = None
        if self._name_enabled and transcribe is not None:
            self.name = NameSpotter(self._aliases, transcribe)

    def prepare(self) -> None:
        """Carrega o Whisper (lento na primeira vez). Falha desliga só a ativação por nome."""
        if self.name is None:
            try:
                self.name = NameSpotter(self._aliases, whisper_transcriber(self._model))
            except Exception as exc:
                print(f"Aviso: ativação por nome indisponível ({exc}). Palmas, atalho e botão continuam.")
                self._name_enabled = False

    def configure(self, clap: bool | None = None, name: bool | None = None) -> None:
        if clap is not None:
            self.clap_on = bool(clap)
        if name is not None:
            self.name_on = bool(name)

    def reset(self) -> None:
        for detector in (self.clap, self.name):
            if detector is not None:
                detector.reset()

    def run_once(self) -> None:
        frame = self.audio.read(timeout=0.1)
        if frame is None:
            return
        self._frames += 1
        now = self._frames * FRAME_SECONDS
        if self.clap_on and self.clap.feed(frame, now):
            self.reset()
            return self.on_wake("clap")
        if self.name_on and self.name is not None and self.name.feed(frame, now):
            self.reset()
            return self.on_wake("name")
