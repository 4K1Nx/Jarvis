"""Anonymous public TTS sample, decoded in memory; no playback or microphone."""
from pathlib import Path
import asyncio,io,sys,yaml
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.tts import TTS
cfg=yaml.safe_load((Path(__file__).resolve().parents[1]/'config.yaml').read_text(encoding='utf-8'))
tts=TTS(cfg)
blob=asyncio.run(tts._synthesize('Olá. Sou a Viv, pronta para ajudar com calma e carinho.'))
pcm,rate=tts._sf.read(io.BytesIO(blob),dtype='float32')
assert len(pcm)>0
print('TTS OK:',cfg['tts']['voice'],'rate',cfg['tts']['rate'],'pitch',cfg['tts']['pitch'],'volume',cfg['tts']['volume'],'seconds',round(len(pcm)/rate,2))

# Exercise the actual WebRTC gate with quiet, public synthetic speech.
# No microphone, playback, credentials, or PC commands are involved.
import numpy as np
from scipy.signal import resample_poly
from core.audio_in import AudioInput
from unittest.mock import Mock,patch
from scripts.test_conversation import ConversationTests
if pcm.ndim>1:pcm=pcm.mean(axis=1)
signal=resample_poly(pcm,16000,rate)
signal=np.clip(signal*(.003/max(float(np.sqrt(np.mean(signal**2))),1e-9)),-.007,.007)
signal=np.concatenate([np.zeros(3200),signal,np.zeros(16000)])
encoded=(signal*32767).astype(np.int16).tobytes()
frames=[encoded[i:i+640] for i in range(0,len(encoded)-639,640)]
audio=AudioInput(cfg)
audio.frames=lambda:iter(frames)
utterance=audio.record_utterance()
assert utterance.size>0, audio.last_capture
assert audio.last_capture['peak_rms']<.008
print('Quiet real WebRTC PASS:',audio.last_capture)
o=ConversationTests().make_orch()
o.audio.frames.return_value=iter([bytes(640)])
o.audio.record_utterance.return_value=utterance
o.stt.transcribe.return_value='Olá Viv, vamos conversar sobre estrelas.'
with patch('core.orchestrator.try_fast_path',return_value=None):o.run_forever()
o.stt.transcribe.assert_called_once()
o.llm.chat_stream.assert_called_once()
o.tts.stream_sentences.assert_called_once()
print('Pipeline PASS: captured quiet speech -> Whisper mock -> Gemini mock -> TTS mock')
