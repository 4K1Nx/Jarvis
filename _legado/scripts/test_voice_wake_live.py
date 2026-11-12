"""Public synthetic wake phrases; real local Whisper, no microphone or playback."""
import asyncio,io,sys,time,yaml
from pathlib import Path
import numpy as np
from scipy.signal import resample_poly
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
# Stub dotenv/PC tools before loading the name parser.
from scripts import test_conversation as safe
import faulthandler
faulthandler.cancel_dump_traceback_later()
from core.tts import TTS
from core.stt import STT
from core.orchestrator import wake_request
cfg=yaml.safe_load(Path('config.yaml').read_text(encoding='utf-8'))
tts=TTS(cfg);stt=STT(cfg)
for phrase,should_wake in [('Ei, Viv.',True),('Ei, Vivi.',True),('Ei, Vive.',True),('Viv, me explique as estrelas.',True),('O céu está cheio de estrelas.',False)]:
    blob=asyncio.run(tts._synthesize(phrase))
    pcm,rate=tts._sf.read(io.BytesIO(blob),dtype='float32')
    if pcm.ndim>1:pcm=pcm.mean(axis=1)
    pcm=resample_poly(pcm,16000,rate).astype(np.float32)
    pcm=np.pad(pcm,(3200,8000))
    started=time.perf_counter();heard=stt.transcribe_wake(pcm)
    result=wake_request(heard)
    print('Public fixture:',repr(phrase),'recognized:',repr(heard),'wake:',result is not None,'seconds:',round(time.perf_counter()-started,2))
    assert (result is not None)==should_wake
print('PASS: 5 public wake fixtures; no recording, playback or Gemini call.')
