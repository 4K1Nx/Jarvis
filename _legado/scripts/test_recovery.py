"""Recovery tests: synthetic PCM and real ASGI static route, no real devices."""
import sys,unittest,time
from pathlib import Path
from unittest.mock import patch,Mock
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.playback_echo import PlaybackEcho
from scripts import test_conversation as base
from core.audio_in import AudioInput

class RecoveryTests(unittest.TestCase):
    def fixture(self):
        rng=np.random.default_rng(18)
        reference=rng.normal(0,.15,16000).astype(np.float32)
        echo=PlaybackEcho()
        with patch('core.playback_echo.time.monotonic',return_value=10):echo.begin(reference,16000)
        return echo,reference
    def pcm(self,x):return (np.clip(x,-1,.9999)*32768).astype(np.int16).tobytes()
    def test_delayed_attenuated_echo_rejected(self):
        echo,reference=self.fixture();frame=self.pcm(reference[3200:3520]*.4)
        with patch('core.playback_echo.time.monotonic',return_value=10.3):out=echo.filter(frame)
        self.assertLess(np.max(np.abs(np.frombuffer(out,dtype=np.int16))),5)
    def test_independent_speech_during_playback_preserved(self):
        echo,_=self.fixture();frame=self.pcm(np.random.default_rng(19).normal(0,.1,320))
        with patch('core.playback_echo.time.monotonic',return_value=10.3):out=echo.filter(frame)
        self.assertEqual(out,frame)
    def test_mixed_voice_not_silenced(self):
        echo,ref=self.fixture();user=np.random.default_rng(20).normal(0,.05,320)
        with patch('core.playback_echo.time.monotonic',return_value=10.3):out=echo.filter(self.pcm(ref[3200:3520]*.7+user))
        pcm=np.frombuffer(out,dtype=np.int16)/32768
        self.assertGreater(np.corrcoef(pcm,user)[0,1],.9)
        self.assertGreater(np.sqrt(np.mean(pcm*pcm)),.035)
    def test_echo_tail_and_expiry(self):
        echo,ref=self.fixture();frame=self.pcm(ref[3200:3520]*.4)
        with patch('core.playback_echo.time.monotonic',return_value=10.3):echo.end()
        with patch('core.playback_echo.time.monotonic',return_value=10.4):self.assertNotEqual(echo.filter(frame),frame)
        with patch('core.playback_echo.time.monotonic',return_value=10.9):self.assertEqual(echo.filter(frame),frame)
    def test_microphone_start_idempotent(self):
        with patch('core.audio_in.VAD'),patch('core.audio_in.sd.RawInputStream') as stream:
            audio=AudioInput(base.CFG)
            with patch.object(audio,'resolve_device'):
                audio.start();audio.start()
            stream.assert_called_once();audio.close()
    def test_manual_interrupt_stops_tts_without_confirming(self):
        o=base.ConversationTests().make_orch();o.state='speaking';o.wake_now()
        o.tts.stop.assert_called_once();self.assertTrue(o._interrupted.is_set());self.assertFalse(o._approved)
    def test_websocket_disconnect_releases_subscription(self):
        from fastapi.testclient import TestClient
        import server
        before=len(server.BUS._subs)
        with TestClient(server.app) as client:
            with client.websocket_connect('/ws') as ws:
                server.BUS.emit('state','listening',state='listening')
                self.assertEqual(ws.receive_json()['state'],'listening')
            for _ in range(50):
                if len(server.BUS._subs)==before:break
                time.sleep(.01)
            self.assertEqual(len(server.BUS._subs),before)
    def test_static_javascript_real_route(self):
        from fastapi.testclient import TestClient
        import server
        with TestClient(server.app) as client:
            response=client.get('/static/viv.js')
            self.assertEqual(response.status_code,200)
            self.assertIn('WebSocket',response.text)
            self.assertIn('/api/wake',response.text)

if __name__=='__main__':unittest.main(verbosity=2)
