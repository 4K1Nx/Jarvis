"""Deterministic audio gate checks, no microphone or speaker device."""
import sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import test_conversation as conversation
from core.audio_in import AudioInput

class AudioTests(unittest.TestCase):
    def audio(self,vad=True):
        with patch('core.audio_in.VAD') as factory:
            factory.return_value.is_speech.return_value=vad
            return AudioInput(conversation.CFG)
    @staticmethod
    def frame(amplitude=.08):
        return (np.sin(np.arange(320)*2*np.pi*220/16000)*amplitude*32767).astype(np.int16).tobytes()
    def test_capture_warns_about_clipping(self):
        audio=self.audio()
        audio.frames=lambda:iter([np.full(320,32767,dtype=np.int16).tobytes()]*20)
        audio.record_utterance()
        self.assertGreater(audio.last_capture['peak_rms'],.99)
        self.assertGreater(audio.last_capture['clipping_ratio'],.99)
        self.assertIn('saturação',audio.last_capture['quality'])
    def test_capture_warns_about_low_signal(self):
        audio=self.audio(False)
        audio.frames=lambda:iter([bytes(640)]*20)
        audio.record_utterance()
        self.assertIn('muito baixo',audio.last_capture['quality'])
        self.assertEqual(audio.last_capture['clipping_ratio'],0)
    def test_loud_non_speech_is_rejected(self):
        audio=self.audio(False)
        for _ in range(20):self.assertFalse(audio.speech_triggered(self.frame(.5)))
    def test_low_energy_is_rejected_even_when_vad_positive(self):
        audio=self.audio(True)
        for _ in range(20):self.assertFalse(audio.speech_triggered(self.frame(.001)))
    def test_sustained_speech_required(self):
        audio=self.audio()
        for _ in range(audio.start_frames-1):self.assertFalse(audio.speech_triggered(self.frame()))
        self.assertTrue(audio.speech_triggered(self.frame()))
    def test_sensitivity_changes_gate(self):
        audio=self.audio()
        audio.set_sensitivity('low');self.assertFalse(audio.is_voice(self.frame(.01)))
        audio.set_sensitivity('high');self.assertTrue(audio.is_voice(self.frame(.01)))
        with self.assertRaises(ValueError):audio.set_sensitivity('anything')
    def test_real_webrtc_silence_returns_no_audio(self):
        audio=AudioInput(conversation.CFG)
        audio.frames=lambda:iter([bytes(640)]*210)
        self.assertEqual(audio.record_utterance().size,0)
    def test_single_continuous_burst_is_not_double_clap(self):
        audio=self.audio()
        pulse=np.tile([12000,-12000],160).astype(np.int16).tobytes()
        with patch('core.audio_in.time.monotonic',side_effect=[10,10.25,10.5]):
            self.assertFalse(audio.clap_triggered(pulse))
            self.assertFalse(audio.clap_triggered(pulse))
            self.assertFalse(audio.clap_triggered(pulse))
    def test_empty_capture_never_reaches_whisper(self):
        o=conversation.ConversationTests().make_orch()
        o.audio.frames.return_value=iter([bytes(640)])
        o.audio.record_utterance.return_value=np.zeros(0,dtype=np.float32)
        o.run_forever()
        o.stt.transcribe.assert_not_called()
    def test_voiced_utterance_retained(self):
        audio=self.audio()
        audio.frames=lambda:iter([self.frame()]*20+[bytes(640)]*30)
        self.assertGreater(audio.record_utterance().size,0)
    def test_short_reply_keeps_preroll_voice(self):
        audio=self.audio()
        for _ in range(audio.start_frames):audio.speech_triggered(self.frame())
        audio.frames=lambda:iter([self.frame()]*3+[bytes(640)]*30)
        self.assertGreater(audio.record_utterance().size,0)
    def test_quiet_explicit_speech_survives_vad_gaps(self):
        audio=self.audio()
        quiet=self.frame(.003)
        self.assertTrue(audio.is_voice(quiet))  # quiet speech can now trigger name recognition
        audio.vad.is_speech.side_effect=[i % 3 != 0 for i in range(30)]+[False]*30
        audio.frames=lambda:iter([quiet]*30+[bytes(640)]*30)
        self.assertGreater(audio.record_utterance().size,0)
        self.assertGreaterEqual(audio.last_capture['speech_frames'],10)
    def test_short_transient_after_activation_is_rejected(self):
        audio=self.audio()
        audio.frames=lambda:iter([self.frame()]*3+[bytes(640)]*60)
        self.assertEqual(audio.record_utterance().size,0)
    def test_missing_audio_frames_fails_visibly(self):
        import queue
        audio=self.audio()
        audio.q=Mock();audio.q.get.side_effect=queue.Empty
        with self.assertRaises(RuntimeError):next(audio.frames())
        self.assertEqual(audio.stream_status,'no_frames')
    def test_gemini_probe_does_not_generate_or_use_tools(self):
        from core.llm import LLM
        llm=LLM.__new__(LLM);llm.c={'model':'gemini-2.5-flash'}
        llm.api_key='unit-test-placeholder';llm.client=Mock()
        llm.client.get.return_value.status_code=200
        llm.client.get.return_value.json.return_value={'supportedGenerationMethods':['generateContent']}
        self.assertEqual(llm.verify_connection(),'available')
        llm.client.post.assert_not_called()
        llm.client.get.side_effect=RuntimeError('private diagnostic must not escape')
        self.assertEqual(llm.verify_connection(),'error')
    def test_wake_reports_failed_microphone(self):
        import server
        from fastapi import HTTPException
        o=Mock();o.audio.stream_status='error'
        with patch.dict(server.ORCH,ref=o), patch('server.launch_voice',return_value=False):
            with self.assertRaises(HTTPException) as error:server.wake()
        self.assertEqual(error.exception.status_code,409)
        o.wake_now.assert_not_called()
    def test_status_exposes_only_audio_diagnostics(self):
        import server,time
        o=Mock();o.state='sleeping';o.llm.connection_status='available';o.llm.c={'model':'gemini-3.8-flash'}
        o.metrics=None;o.research=None;o.audio.sensitivity='normal'
        o.audio.stream_status='ok';o.audio.last_frame_at=time.monotonic()
        o.audio.last_capture={'frames':100,'speech_frames':20,'peak_rms':.003}
        with patch.dict(server.ORCH,ref=o):data=server.status()
        self.assertEqual(data['audio_health']['capture']['speech_frames'],20)
        self.assertEqual(data['gemini']['status'],'available')
        self.assertNotIn('api_key',str(data))
    def test_quiet_voice_tolerates_short_vad_gaps(self):
        audio=self.audio()
        audio.vad.is_speech.side_effect=[True,True,False]*4
        detected=[audio.speech_triggered(self.frame(.003)) for _ in range(12)]
        self.assertTrue(detected[-1])
    def test_moderate_double_clap(self):
        audio=self.audio()
        pulse=np.tile([1100,-1100],160).astype(np.int16).tobytes()
        with patch('core.audio_in.time.monotonic',side_effect=[10,10.1,10.3]):
            self.assertFalse(audio.clap_triggered(pulse))
            self.assertFalse(audio.clap_triggered(bytes(640)))
            self.assertTrue(audio.clap_triggered(pulse))
    def test_first_clap_is_not_consumed_as_voice_activation(self):
        audio=self.audio()
        pulse=np.tile([1100,-1100],160).astype(np.int16).tobytes()
        with patch('core.audio_in.time.monotonic',return_value=10):
            self.assertFalse(audio.clap_triggered(pulse))
        with patch('core.audio_in.time.monotonic',return_value=10.1):
            audio.clap_triggered(bytes(640))
            for _ in range(10):self.assertFalse(audio.speech_triggered(self.frame()))
        with patch('core.audio_in.time.monotonic',return_value=10.3):
            self.assertTrue(audio.clap_triggered(pulse))
if __name__=='__main__':unittest.main(verbosity=2)
