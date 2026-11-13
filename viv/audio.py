"""Entrada e saída de áudio com dois streams que ficam abertos durante toda a execução.

Interromper a fala é esvaziar o buffer de reprodução; nenhum stream é fechado no
meio do uso. Só `stop()` fecha os streams.
"""
import queue
import threading
import time
from collections import deque
from typing import Callable

import numpy as np

from viv.bus import BUS

IN_RATE, OUT_RATE = 16000, 24000
FRAME_SAMPLES = 320                      # 20 ms a 16 kHz
RECENT_FRAMES = 6 * IN_RATE // FRAME_SAMPLES
HANGOVER = 0.6                           # s em que "tocando" continua valendo após o fim do áudio
OPEN_FRAMES = 3                          # quadros seguidos acima do limiar (60 ms) para abrir o microfone
HOLD = 0.6                               # s em que o microfone segue aberto depois da última fala forte
SPEECH_RMS = 0.008                       # acima disto o quadro conta como fala do usuário
SPEECH_FRAMES = 15 * IN_RATE // FRAME_SAMPLES   # até 15 s de fala por turno, para reconhecer a voz
ECHO_WARMUP = 0.4                        # s iniciais de cada fala em que a Viv só mede o próprio eco
ECHO_MARGIN = 1.6                        # o usuário precisa falar isto acima do eco medido para interromper
ECHO_DECAY = 0.995                       # o eco medido cai devagar (metade em ~3 s) e segue o volume da caixa
HEADPHONE_FACTOR = 0.25                 # com fones, o limiar cai para um quarto: ainda barra o vazamento


class AudioError(RuntimeError):
    pass


def rms(frame: bytes) -> float:
    if not frame:
        return 0.0
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(samples * samples)))


def resolve_input(devices: list[dict], name: str | None) -> int | None:
    """Índice do microfone cujo nome casa com `name`; None = padrão do sistema."""
    if not name:
        return None
    wanted = name.casefold()
    inputs = [d for d in devices if d.get("max_input_channels", 0) > 0]
    for exact in (True, False):
        for device in inputs:
            found = device.get("name", "").casefold()
            if (found == wanted) if exact else (wanted in found):
                return device["index"]
    return None


def echo_gate(rms_value: float, playing: bool, headphones: bool, threshold: float) -> bool:
    """O quadro tem volume de fala do usuário? Enquanto a Viv fala, só conta o que passa do
    limiar, para o microfone não captar a própria Viv. Com fones o limiar é bem menor, mas
    existe: fone aberto ou alto vaza som para o microfone."""
    return not playing or rms_value >= (threshold * HEADPHONE_FACTOR if headphones else threshold)


class AudioIO:
    FRAME_BYTES = FRAME_SAMPLES * 2

    def __init__(self, cfg: dict, clock: Callable[[], float] = time.monotonic):
        a = cfg.get("audio", {})
        self._device_name = a.get("input_device_name")
        self._headphones = bool(a.get("headphones", False))
        self._threshold = float(a.get("barge_in_rms", 0.08))
        self._clock = clock
        self.input_name = ""
        self._in_q: queue.Queue = queue.Queue(maxsize=250)   # 5 s de folga
        self._recent: deque = deque(maxlen=RECENT_FRAMES)
        self._speech: deque = deque(maxlen=SPEECH_FRAMES)
        self._out = bytearray()
        self._out_lock = threading.Lock()
        self._last_out = float("-inf")
        self._loud = 0                         # quadros fortes seguidos enquanto a Viv fala
        self._echo = 0.0                       # nível com que a voz da Viv volta pelo microfone
        self._play_start: float | None = None  # quando a fala atual começou a tocar
        self._open_until = float("-inf")       # até quando o microfone fica aberto durante a fala dela
        self._last_level = {"mic": 0.0, "out": 0.0}
        self._streams: list = []

    def configure(self, headphones: bool | None = None, threshold: float | None = None) -> None:
        if headphones is not None:
            self._headphones = bool(headphones)
        if threshold is not None:
            self._threshold = float(threshold)

    # ---- ciclo de vida -------------------------------------------------
    def start(self) -> None:
        import sounddevice as sd
        try:
            devices = [dict(d) for d in sd.query_devices()]
            index = resolve_input(devices, self._device_name)
            default_in = sd.default.device[0]
            self.input_name = devices[index if index is not None else default_in]["name"]
            if index is None and self._device_name:
                BUS.emit("card", "Microfone configurado não encontrado", kind="data",
                         body=f"Usando o padrão: {self.input_name}", ok=True)
            inp = sd.RawInputStream(samplerate=IN_RATE, blocksize=FRAME_SAMPLES, channels=1, dtype="int16",
                                    device=index, callback=self._on_input)
            out = sd.RawOutputStream(samplerate=OUT_RATE, blocksize=480, channels=1, dtype="int16",
                                     callback=self._on_output)
            inp.start(); out.start()
            self._streams = [inp, out]
        except Exception as exc:
            raise AudioError(f"Não foi possível abrir o áudio: {exc}. Confira o microfone e as caixas "
                             "nas configurações de som do Windows.") from exc

    def stop(self) -> None:
        streams, self._streams = self._streams, []
        for stream in streams:
            try:
                stream.stop(); stream.close()
            except Exception:
                pass

    # ---- callbacks (thread de áudio) -----------------------------------
    def _on_input(self, indata, frames, time_info, status) -> None:
        frame = bytes(indata)
        self._recent.append(frame)
        try:
            self._in_q.put_nowait(frame)
        except queue.Full:                      # ninguém lendo: descarta o mais antigo
            try:
                self._in_q.get_nowait()
            except queue.Empty:
                pass
            self._in_q.put_nowait(frame)
        self._level("mic", rms(frame))

    def _on_output(self, outdata, frames, time_info, status) -> None:
        need = frames * 2
        with self._out_lock:
            chunk = bytes(self._out[:need])
            del self._out[:need]
        if chunk:
            self._last_out = self._clock()
        outdata[:len(chunk)] = chunk
        outdata[len(chunk):need] = bytes(need - len(chunk))
        self._level("out", rms(chunk))

    def _level(self, source: str, value: float) -> None:
        now = self._clock()
        if now - self._last_level[source] >= 0.05:
            self._last_level[source] = now
            BUS.emit("level", value=min(1.0, value * 4), source=source)

    # ---- API -----------------------------------------------------------
    def read(self, timeout: float = 0.1) -> bytes | None:
        try:
            return self._in_q.get(timeout=timeout)
        except queue.Empty:
            return None

    def play(self, pcm: bytes) -> None:
        with self._out_lock:
            self._out += pcm

    def flush(self) -> None:
        with self._out_lock:
            self._out.clear()

    def is_playing(self) -> bool:
        with self._out_lock:
            if self._out:
                return True
        return self._clock() - self._last_out < HANGOVER

    def recent(self, seconds: float = 6.0) -> np.ndarray:
        frames = list(self._recent)[-max(1, int(seconds * IN_RATE / FRAME_SAMPLES)):]
        if not frames:
            return np.zeros(0, dtype=np.float32)
        return np.frombuffer(b"".join(frames), dtype=np.int16).astype(np.float32) / 32768.0

    def should_send(self, frame: bytes) -> bool:
        """Enviar este quadro ao modelo? Fora da fala da Viv, sempre. Durante a fala dela, o
        microfone só abre com fala sustentada (um estalo isolado não conta) e fica aberto por
        HOLD segundos, para a frase do usuário não chegar picotada.

        Sem fones, a voz da Viv volta pelo microfone e pode passar do limiar fixo: ela se ouviria
        e se interromperia. Por isso o eco é medido — no começo de cada fala (ECHO_WARMUP), quando
        nada abre o microfone, e depois em todo quadro que não o abre — e interromper exige falar
        ECHO_MARGIN vezes acima dele."""
        level = rms(frame)
        if not self.is_playing():
            self._loud, self._open_until, self._play_start = 0, float("-inf"), None
            send = True
        else:
            now = self._clock()
            if self._play_start is None:
                self._play_start = now
            warming = not self._headphones and now - self._play_start < ECHO_WARMUP
            over = echo_gate(level, True, self._headphones, self._threshold) and level >= self._echo * ECHO_MARGIN
            if over and not warming:
                self._loud += 1
                if self._loud >= OPEN_FRAMES:
                    self._open_until = now + HOLD
            else:
                self._loud = 0
                if now >= self._open_until:          # com o microfone aberto é o usuário falando, não o eco
                    self._echo = max(level, self._echo * ECHO_DECAY)
            send = now < self._open_until
        if send and level >= SPEECH_RMS:
            self._speech.append(frame)
        return send

    def take_speech(self) -> np.ndarray:
        """Fala do usuário desde a última chamada: só os quadros enviados ao modelo e com voz,
        sem silêncio nem a voz da Viv. É o que o reconhecimento de voz analisa."""
        frames = []
        while self._speech:
            frames.append(self._speech.popleft())
        if not frames:
            return np.zeros(0, dtype=np.float32)
        return np.frombuffer(b"".join(frames), dtype=np.int16).astype(np.float32) / 32768.0

    def beep(self, kind: str) -> None:
        notes = {"wake": (660, 880), "sleep": (880, 660), "error": (220, 196)}.get(kind, (660,))
        t = np.arange(int(OUT_RATE * 0.09)) / OUT_RATE
        fade = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.01)
        tone = np.concatenate([np.sin(2 * np.pi * f * t) * fade for f in notes])
        self.play((tone * 0.2 * 32767).astype(np.int16).tobytes())
