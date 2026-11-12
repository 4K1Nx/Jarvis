import unittest
from unittest.mock import patch
import numpy as np
from scripts.enroll_voice import validate_clip,record

class EnrollTests(unittest.TestCase):
    def test_reject_silent_short_clipped(self):
        for audio in (np.zeros(50000),np.ones(100),np.ones(50000)):
            with self.assertRaises(ValueError):validate_clip(audio)
    def test_accepts_clear_synthetic_signal(self):
        audio=.03*np.sin(np.arange(48000)*.1)
        self.assertEqual(len(validate_clip(audio)),48000)
    def test_record_uses_explicit_microphone(self):
        with patch('sounddevice.rec',return_value=(.03*np.sin(np.arange(48000)*.1))[:,None]) as rec,patch('sounddevice.wait'):
            record(3,18)
        self.assertEqual(rec.call_args.kwargs['device'],18)

if __name__=='__main__':unittest.main()
