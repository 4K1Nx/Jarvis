import sys,unittest,threading
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import test_conversation as base
from core.audio_in import AudioInput

class AudioRecoveryTests(unittest.TestCase):
    def test_filter_failure_keeps_callback_alive_with_silence(self):
        with patch('core.audio_in.VAD'),patch('core.audio_in.sd.RawInputStream') as factory:
            audio=AudioInput(base.CFG)
            with patch.object(audio,'resolve_device'):audio.start()
            cb=factory.call_args.kwargs['callback']
            audio.echo.filter=Mock(side_effect=ValueError('private'))
            cb(bytes([1])*640,320,None,None)
            self.assertEqual(audio.q.get_nowait(),bytes(640));self.assertEqual(audio.filter_errors,1)
            audio.echo.filter=Mock(return_value=bytes([2])*640)
            cb(bytes(640),320,None,None)
            self.assertEqual(audio.q.get_nowait(),bytes([2])*640)
            audio.close()
    def test_live_worker_is_never_duplicated(self):
        import server
        old=Mock();old.is_alive.return_value=True
        with patch.object(server,'_voice_thread',old),patch('server.threading.Thread') as factory:
            self.assertFalse(server.launch_voice(Mock()));factory.assert_not_called()
    def test_wake_recovers_failed_capture(self):
        import server
        o=Mock();o.audio.stream_status='error'
        with patch.dict(server.ORCH,ref=o),patch('server.launch_voice',return_value=True) as launch:
            self.assertEqual(server.wake(),{'ok':True})
            launch.assert_called_once_with(o);o.wake_now.assert_called_once()
    def test_failed_loop_closes_then_can_restart(self):
        import server
        o=Mock();o.run_forever.side_effect=RuntimeError('private')
        with patch.object(server,'_voice_thread',None),patch('core.startup_diagnostics.failure') as failure:
            self.assertTrue(server.launch_voice(o));server._voice_thread.join(2)
            self.assertFalse(server._voice_thread.is_alive());o.audio.close.assert_called_once()
            self.assertEqual(o.audio.stream_status,'error');failure.assert_called_once()
            self.assertTrue(server.launch_voice(o));server._voice_thread.join(2)
            self.assertEqual(o.audio.close.call_count,2)

class TurnFailureTests(unittest.TestCase):
    def test_gemini_404_is_explained_without_retrying_actions(self):
        from core.llm import GeminiFailure
        o=base.ConversationTests().make_orch()
        with patch('core.startup_diagnostics.failure') as log:
            o._report_turn_failure(GeminiFailure('model_not_found'))
        self.assertEqual(o.state,'unavailable')
        self.assertIn('HTTP 404',o.tts.say.call_args.args[0])
        o.llm.chat_stream.assert_not_called()
        log.assert_called_once()

    def test_failure_of_spoken_diagnostic_is_contained(self):
        o=base.ConversationTests().make_orch()
        o.tts.say.side_effect=RuntimeError('private audio error')
        with patch('core.startup_diagnostics.failure') as log:
            o._report_turn_failure(ValueError('secret content'))
        self.assertEqual(o.state,'error')
        self.assertNotIn('secret',o.tts.say.call_args.args[0])
        self.assertEqual(log.call_count,2)

    def test_startup_gap_announcement_is_opt_in(self):
        source=(Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8')
        self.assertIn('cfg.get("assistant", {}).get("announce_gaps_on_start", False) and orch.gaps.count()',source)

if __name__=='__main__':unittest.main(verbosity=2)
