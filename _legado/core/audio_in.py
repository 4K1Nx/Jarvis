"""Microphone ingestion: 20 ms frames -> wake word -> VAD endpointing."""
import queue, time, numpy as np, sounddevice as sd
from collections import deque
from core.bus import BUS
from core.vad import VAD


class AudioInput:
    def __init__(self, cfg: dict):
        a = cfg["audio"]
        self.rate = a["sample_rate"]
        self.frame = int(self.rate * a["frame_ms"] / 1000)
        self.vad = VAD(cfg)   # Silero on CPU
        self.silence_frames = a["silence_ms_to_endpoint"] // a["frame_ms"]
        self.device = a["input_device"]
        self.device_name = a.get("input_device_name")
        self.hostapi_name = a.get("input_hostapi", "MME")
        self.resolved_name = None
        self.q: "queue.Queue[bytes]" = queue.Queue()
        self._stream = None
        from core.playback_echo import PlaybackEcho
        self.echo = PlaybackEcho(self.rate)
        self.frame_ms = a['frame_ms']
        self.sensitivity = a.get('sensitivity', 'normal')
        self.min_speech_frames = max(1, a.get('min_speech_ms', 200) // self.frame_ms)
        self.start_frames = max(1, a.get('speech_start_ms', 160) // self.frame_ms)
        self.wait_frames = a.get('speech_wait_ms', 4000) // self.frame_ms
        self._speech_run = 0
        self._ambient = 0.0003
        self._speech_window = deque(maxlen=self.start_frames * 2)
        self.last_frame_at = None
        self.stream_status = "not_started"
        self.last_capture = {}
        self.filter_errors = 0
        self._pre_roll = deque(maxlen=max(1, 600 // self.frame_ms))
        self._clap_high = False
        self.clap_enabled = bool(cfg.get("wakeword", {}).get("clap_to_wake", False))
        self.clap_min_gap = cfg.get("wakeword", {}).get("clap_min_gap_ms", 120) / 1000.0
        self.clap_max_gap = cfg.get("wakeword", {}).get("clap_max_gap_ms", 700) / 1000.0
        self.clap_cooldown = cfg.get("wakeword", {}).get("clap_cooldown_ms", 1200) / 1000.0
        self._last_clap = 0.0
        self._clap_times = []
        self._noise_floor = 0.001

    def resolve_device(self):
        """Resolve a stable name each startup; never fall back to another microphone."""
        if self.device_name:
            hosts = sd.query_hostapis()
            matches = [(i, d) for i, d in enumerate(sd.query_devices())
                       if d['max_input_channels'] > 0
                       and d['name'].casefold() == self.device_name.casefold()
                       and hosts[d['hostapi']]['name'].casefold() == self.hostapi_name.casefold()]
            if len(matches) != 1:
                raise RuntimeError('Microfone configurado ausente ou ambíguo. Confira audio.input_device_name e input_hostapi.')
            self.device, info = matches[0]
        else:
            info = sd.query_devices(self.device, 'input')
        self.resolved_name = info['name']
        sd.check_input_settings(device=self.device, channels=1, dtype='int16', samplerate=self.rate)
        return self.device

    def start(self):
        if self._stream is not None:
            return
        from core.startup_diagnostics import stage
        stage('Resolvendo dispositivo de entrada')
        self.resolve_device()
        def cb(indata, frames, t, status):
            self.last_frame_at = time.monotonic()
            self.stream_status = "overflow" if status else "ok"
            raw = bytes(indata)
            try:
                filtered = self.echo.filter(raw)
            except Exception:
                # A callback exception stops PortAudio delivery. Keep the stream alive
                # but suppress this frame rather than feeding unfiltered playback back.
                self.filter_errors += 1
                filtered = bytes(len(raw))
            self.q.put(filtered)

        self._stream = sd.RawInputStream(
            samplerate=self.rate, blocksize=self.frame, dtype="int16",
            channels=1, callback=cb, device=self.device,
        )
        self._stream.start()
        stage("Microfone iniciado")
        BUS.emit("sys", f"audio input open @ {self.rate} Hz")

    def frames(self):
        while True:
            try:
                yield self.q.get(timeout=3)
            except queue.Empty:
                self.stream_status = "no_frames"
                raise RuntimeError("Microfone sem quadros de áudio") from None

    def discard_pending(self):
        """Drop audio captured during reasoning/playback before the next turn."""
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                break
        self._clap_times.clear()
        self._pre_roll.clear()
        self._speech_window.clear()
        self._speech_run = 0

    def level(self, frame: bytes) -> float:
        x = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        return float(min(1.0, np.sqrt((x ** 2).mean()) * 6.0))


    def set_sensitivity(self, value):
        if value not in ('low', 'normal', 'high'):
            raise ValueError('Sensibilidade inválida')
        self.sensitivity = value
        self._speech_run = 0

    def is_voice(self, frame, capturing=False):
        pcm = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(pcm * pcm))) if len(pcm) else 0.0
        vad = self.vad.is_speech(frame)
        minimum, factor = {'low': (.012, 3.5), 'normal': (.0015, 2.0), 'high': (.0006, 1.5)}.get(self.sensitivity, (.008, 2.5))
        if not vad:
            self._ambient = .98 * self._ambient + .02 * min(rms, .03)
        # Once explicitly activated, WebRTC decides speech; the energy guard only
        # excludes near-digital silence. The stronger gate remains for auto-wake.
        threshold = 0.00015 if capturing else max(minimum, self._ambient * factor)
        return bool(vad and rms >= threshold)

    def speech_triggered(self, frame):
        self._pre_roll.append(frame)
        # Give the second clap its detection window before starting speech capture.
        if self._clap_times and time.monotonic() - self._clap_times[-1] <= self.clap_max_gap:
            self._speech_window.clear()
            self._speech_run = 0
            return False
        self._speech_window.append(self.is_voice(frame))
        self._speech_run = sum(self._speech_window)
        return self._speech_run >= self.start_frames

    def clap_triggered(self, frame: bytes) -> bool:
        """Best-effort double-clap detector using transient RMS + zero-crossing rate."""
        if not self.clap_enabled:
            return False
        now = time.monotonic()
        if now - self._last_clap < self.clap_cooldown:
            return False
        x = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(x * x)) + 1e-9)
        zcr = float(np.mean(x[:-1] * x[1:] < 0)) if len(x) > 1 else 0.0
        # A clap is a short, loud, broadband transient. These thresholds are intentionally conservative.
        high = rms > max(0.018, self._noise_floor * 4.0) and zcr > 0.12
        rising = high and not self._clap_high
        self._clap_high = high
        if rising:
            self._clap_times = [t for t in self._clap_times if now - t <= self.clap_max_gap]
            if not self._clap_times or now - self._clap_times[-1] >= self.clap_min_gap:
                self._clap_times.append(now)
                if len(self._clap_times) >= 2:
                    self._clap_times.clear()
                    self._last_clap = now
                    BUS.emit("wake", "double-clap wake triggered")
                    return True
        elif not high:
            self._noise_floor = self._noise_floor * 0.98 + min(rms, .015) * 0.02
        return False

    def record_utterance(self, max_seconds: float = 15.0):
        """Collect frames until the VAD reports sustained silence."""
        collected = list(self._pre_roll)
        self._pre_roll.clear()
        quiet = 0
        voiced_count = min(self._speech_run, len(collected))
        recent = deque([True] * self._speech_run, maxlen=self.start_frames * 2)
        peak_rms = 0.0
        frame_count = 0
        spoke = self._speech_run >= self.start_frames
        self._speech_run = 0
        limit = int(max_seconds * self.rate / self.frame)
        for i, frame in enumerate(self.frames()):
            collected.append(frame)
            voiced = self.is_voice(frame, capturing=True)
            frame_count += 1
            samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
            peak_rms = max(peak_rms, float(np.sqrt(np.mean(samples * samples))))
            voiced_count += int(voiced)
            recent.append(voiced)
            spoke = spoke or sum(recent) >= self.start_frames
            quiet = 0 if voiced else quiet + 1
            BUS.emit('level', '', value=self.level(frame), source='microphone')
            if spoke and quiet >= self.silence_frames:
                break
            if not spoke and i >= self.wait_frames:
                break
            if i >= limit:
                break
        all_samples = np.frombuffer(b''.join(collected), dtype=np.int16).astype(np.float32) / 32768.0
        clipping = float(np.mean(np.abs(all_samples) >= .99)) if len(all_samples) else 0.0
        quality = ('Possível saturação: reduza o ganho do microfone.' if clipping > .005 else
                   'Sinal muito baixo: confira entrada, distância e ganho.' if peak_rms < .001 else
                   'Nível detectado; a precisão da transcrição precisa ser conferida.')
        self.last_capture = {'frames': frame_count, 'speech_frames': voiced_count,
                             'peak_rms': round(peak_rms, 6), 'clipping_ratio': round(clipping, 5), 'quality': quality}
        BUS.emit('audio_diagnostic', '', **self.last_capture)
        if not spoke or voiced_count < self.min_speech_frames:
            return np.zeros(0, dtype=np.float32)
        pcm = b''.join(collected)
        return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

    def close(self):
        if self._stream:
            self._stream.stop(); self._stream.close()
            self._stream = None
