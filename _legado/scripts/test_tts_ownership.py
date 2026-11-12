"""Regression for native crash when sd.stop races playback cleanup."""
import sys,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.tts import TTS

class PlaybackTests(unittest.TestCase):
    def tts(self):
        obj=TTS.__new__(TTS);obj._cancel=threading.Event();obj.on_audio=None;obj.on_playback=None
        return obj
    def test_interrupt_does_not_call_global_driver_stop(self):
        obj=self.tts()
        with patch('core.tts.sd.stop') as stop:
            t=threading.Thread(target=obj.stop);t.start();t.join()
            stop.assert_not_called();self.assertTrue(obj._cancel.is_set())
    def test_cancellation_and_cleanup_stay_on_playback_thread(self):
        obj=self.tts();owner=threading.get_ident();calls=[]
        def record(name):calls.append((name,threading.get_ident()))
        stream=Mock()
        stream.start.side_effect=lambda:record('start')
        def write(data):
            record('write');t=threading.Thread(target=obj.stop);t.start();t.join()
        stream.write.side_effect=write
        stream.abort.side_effect=lambda:record('abort')
        stream.close.side_effect=lambda:record('close')
        with patch('core.tts.sd.OutputStream',return_value=stream):obj._play_audio(np.zeros(24000,dtype=np.float32),24000)
        self.assertEqual([x[0] for x in calls],['start','write','abort','close'])
        self.assertTrue(all(t==owner for _,t in calls));stream.stop.assert_not_called()
    def test_write_failure_closes_stream(self):
        obj=self.tts();stream=Mock();stream.write.side_effect=RuntimeError('simulated')
        with patch('core.tts.sd.OutputStream',return_value=stream),self.assertRaises(RuntimeError):obj._play_audio(np.zeros(1000,dtype=np.float32),24000)
        stream.close.assert_called_once()
    def test_normal_completion_and_pre_cancel(self):
        obj=self.tts();stream=Mock()
        with patch('core.tts.sd.OutputStream',return_value=stream) as factory:
            obj._play_audio(np.zeros(1000,dtype=np.float32),24000)
            self.assertEqual(stream.write.call_count,3);stream.stop.assert_called_once();stream.close.assert_called_once()
            obj.stop();obj._play_audio(np.zeros(1000,dtype=np.float32),24000)
            factory.assert_called_once()

if __name__=='__main__':unittest.main(verbosity=2)
