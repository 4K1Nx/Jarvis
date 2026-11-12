"""Edge TTS speech with in-memory decoding and serialized playback."""
import asyncio
import io
import re
import threading
import numpy as np
import sounddevice as sd
from core.bus import BUS
from core.metrics import measure, playback_started

SENT_END = re.compile(r"(?<=[.!?])\s+")


class TTS:
    def __init__(self, cfg):
        self.cfg = cfg['tts']
        self.on_playback = None
        self.on_playback_end = None
        self.on_audio = None
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        import edge_tts
        import soundfile
        self._edge = edge_tts
        self._sf = soundfile
        BUS.emit('tts', f"Edge TTS pronto · {self.cfg['voice']}")

    async def _synthesize(self, text):
        data = bytearray()
        speech = self._edge.Communicate(text, self.cfg['voice'], rate=self.cfg.get('rate', '-5%'), pitch=self.cfg.get('pitch', '+3Hz'), volume=self.cfg.get('volume', '-3%'))
        async for chunk in speech.stream():
            if self._cancel.is_set():
                return None
            if chunk['type'] == 'audio':
                data.extend(chunk['data'])
        if not data:
            raise RuntimeError('Edge TTS não retornou áudio. Verifique a conexão.')
        return bytes(data)

    def stop(self):
        self._cancel.set()
        # Never touch PortAudio from the listening/UI thread.
        # The playback owner observes this event between short writes.

    def say(self, text):
        if not text.strip():
            return
        with self._lock:
            from core.startup_diagnostics import stage
            stage('Sintetizando resposta de voz')
            self._cancel.clear()
            with measure('tts_generate_ms'):
                data = asyncio.run(self._synthesize(text))
            if data is None or self._cancel.is_set():
                return
            stage('Decodificando resposta de voz')
            with measure('tts_decode_ms'):
                samples, rate = self._sf.read(io.BytesIO(data), dtype='float32')
            BUS.emit('tts', f'Viv: {text}')
            BUS.emit('level', '', value=float(min(1, np.abs(samples).mean() * 8)), source='playback')
            try:
                with measure('tts_playback_ms'):
                    stage('Iniciando reproducao de voz')
                    self._play_audio(samples, rate)
            finally:
                if self.on_playback_end:
                    self.on_playback_end()
                BUS.emit('level', '', value=0.0, source='playback')

    def _play_audio(self, samples, rate):
        """All output stream operations belong to this thread, including cancellation."""
        pcm = np.asarray(samples, dtype=np.float32)
        if pcm.ndim == 1:
            pcm = pcm[:, None]
        block = max(1, int(rate * .02))
        if self._cancel.is_set() or not len(pcm):
            return
        stream = sd.OutputStream(samplerate=rate, channels=pcm.shape[1],
                                 dtype='float32', blocksize=block)
        try:
            stream.start()
            if self.on_audio:
                self.on_audio(pcm, rate)
            playback_started()
            if self.on_playback:
                self.on_playback()
            else:
                BUS.emit('state', 'speaking', state='speaking')
            for offset in range(0, len(pcm), block):
                if self._cancel.is_set():
                    break
                stream.write(pcm[offset:offset + block])
            if self._cancel.is_set():
                stream.abort()
            else:
                stream.stop()
        finally:
            stream.close()

    def stream_sentences(self, token_iter, stop=None):
        if not self.cfg.get('sentence_streaming', True):
            parts = []
            for tok in token_iter:
                if stop is not None and stop.is_set():
                    return ''.join(parts)
                parts.append(tok)
            full = ''.join(parts)
            if full.strip() and not (stop is not None and stop.is_set()):
                self.say(full)
            return full
        buf, full = '', ''
        for tok in token_iter:
            if stop is not None and stop.is_set():
                break
            buf += tok
            full += tok
            parts = SENT_END.split(buf)
            for part in parts[:-1]:
                if stop is not None and stop.is_set():
                    return full
                self.say(part.strip())
            buf = parts[-1]
        if buf.strip() and not (stop is not None and stop.is_set()):
            self.say(buf.strip())
        return full
