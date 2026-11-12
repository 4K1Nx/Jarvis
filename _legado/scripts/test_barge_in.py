"""Synthetic microphone frames only; no real input, output or OS actions."""
import sys, unittest, queue
from pathlib import Path
from collections import deque
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.barge_in import BargeIn
from scripts import test_conversation as base
from core.audio_in import AudioInput
from unittest.mock import patch

class BargeTests(unittest.TestCase):
    def audio(self):
        a=Mock();a.frame_ms=20;a.q=queue.Queue();a._pre_roll=deque(maxlen=30)
        a.is_voice.side_effect=lambda frame: frame==b'voice'
        a.level.return_value=.1
        return a
    def test_speech_stops_playback_and_preserves_onset(self):
        a=self.audio();interrupt=Mock();monitor=BargeIn(a,interrupt)
        for _ in range(12):a.q.put(b'voice')
        monitor.start();monitor.thread.join(1);monitor.finish()
        interrupt.assert_called_once();self.assertEqual(list(a._pre_roll),[b'voice']*12)
        self.assertEqual(a._speech_run,12)
    def test_noise_and_short_burst_do_not_interrupt(self):
        a=self.audio();interrupt=Mock();monitor=BargeIn(a,interrupt)
        for f in [b'noise']*20+[b'voice']*3+[b'noise']:a.q.put(f)
        monitor.start();monitor.done.wait(.1);monitor.finish()
        interrupt.assert_not_called();self.assertFalse(monitor.thread.is_alive())
    def test_interrupt_flags_next_turn_and_stops_sentence_stream(self):
        o=base.ConversationTests().make_orch();o._interrupt_playback()
        o.tts.stop.assert_called_once();self.assertTrue(o._interrupted.is_set())
        self.assertTrue(o._stop_speaking.is_set());self.assertEqual(o.state,'listening')
    def test_longer_preroll_retains_onset(self):
        with patch('core.audio_in.VAD'):
            a=AudioInput(base.CFG)
        self.assertGreaterEqual(a._pre_roll.maxlen*a.frame_ms,600)
    def test_confirmation_does_not_start_second_capture(self):
        o=base.ConversationTests().make_orch();o.pending={'tool':'system.kill'}
        o._playback_started();self.assertIsNone(o._barge)

if __name__=='__main__':unittest.main(verbosity=2)
