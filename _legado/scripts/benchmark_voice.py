"""Public synthetic voice benchmark. No microphone, playback, dotenv or Gemini key."""
import asyncio
import io
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yaml
from scipy.signal import resample_poly
from core.tts import TTS
from core.stt import STT
from core.metrics import TurnTrace, measure

cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / 'config.yaml').read_text(encoding='utf-8'))
phrases = ['Olá, eu sou a Viv.', 'O céu parece azul durante o dia.']
tts = TTS(cfg)
results = {}
for label, chunks in [('separate_sentences', phrases), ('single_request', [' '.join(phrases)])]:
    trace = TurnTrace()
    with trace.activate():
        for phrase in chunks:
            with measure('tts_generate_ms'):
                audio = asyncio.run(tts._synthesize(phrase))
            with measure('tts_decode_ms'):
                pcm, rate = tts._sf.read(io.BytesIO(audio), dtype='float32')
    results[label] = trace.finish()
# Last audio is public, generated above; reuse exactly the same input for both passes.
wave = resample_poly(pcm, 16000, rate).astype('float32')
start = time.perf_counter()
stt = STT(cfg)  # local_files_only=True; no model download
results['model_load_ms'] = (time.perf_counter() - start) * 1000
results['audio_seconds'] = len(wave) / 16000
for label in ['first_transcription', 'warm_transcription']:
    trace = TurnTrace()
    with trace.activate():
        with measure('whisper_ms'):
            transcript = stt.transcribe(wave)
    if not transcript:
        raise SystemExit('Whisper returned empty text')
    results[label] = trace.finish()
print(json.dumps(results, indent=2))
