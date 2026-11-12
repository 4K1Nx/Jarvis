"""Offline wake and stable microphone regressions: no audio devices opened."""
import sys,unittest,copy
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import test_conversation as conversation
CFG=copy.deepcopy(conversation.CFG)
CFG['audio']['input_device_name']='Microfone (Realtek(R) Audio)'
from core.audio_in import AudioInput
from core.orchestrator import wake_request

class WakeTests(unittest.TestCase):
    def audio(self):
        with patch('core.audio_in.VAD'):return AudioInput(CFG)
    def test_realtek_is_resolved_after_index_changes(self):
        devices=[{'name':'Microfone (2- Wireless Controller)','max_input_channels':2,'hostapi':0},
                 {'name':'Microfone (Realtek(R) Audio)','max_input_channels':2,'hostapi':1},
                 {'name':'Microfone (Realtek(R) Audio)','max_input_channels':2,'hostapi':0}]
        audio=self.audio()
        with patch('core.audio_in.sd.query_devices',return_value=devices),patch('core.audio_in.sd.query_hostapis',return_value=[{'name':'MME'},{'name':'Windows WASAPI'}]),patch('core.audio_in.sd.check_input_settings') as check,patch('core.audio_in.sd.RawInputStream') as stream:
            self.assertEqual(audio.resolve_device(),2)
            check.assert_called_once_with(device=2,channels=1,dtype='int16',samplerate=16000)
            stream.assert_not_called()
    def test_missing_realtek_never_falls_back_to_controller(self):
        audio=self.audio()
        with patch('core.audio_in.sd.query_devices',return_value=[]),patch('core.audio_in.sd.query_hostapis',return_value=[]),patch('core.audio_in.sd.RawInputStream') as stream:
            with self.assertRaises(RuntimeError):audio.start()
            stream.assert_not_called()
    def test_only_direct_name_activates(self):
        for text in ['Viv','Ei, Viv!','Olá, Vivi.','Ei, vive!','Vive.']:
            self.assertEqual(wake_request(text),'')
        self.assertEqual(wake_request('Viv, me explique as estrelas.'),'me explique as estrelas.')
        for text in ['viver é bom','Eu vi um filme','A Viv está dormindo','dividir','primeiro','vive em uma cidade']:
            self.assertIsNone(wake_request(text))
    def orch(self,heard):
        o=conversation.ConversationTests().make_orch()
        o.wake.enabled=False;o.audio.clap_triggered.return_value=False
        o.audio.speech_triggered.return_value=True
        o.audio.frames.return_value=iter([bytes(640),bytes(640)])
        from concurrent.futures import Future
        def immediate(fn,audio):
            result=Future();result.set_result(fn(audio));return result
        o._wake_pool=Mock();o._wake_pool.submit.side_effect=immediate
        o.audio.record_utterance.return_value=np.ones(16000,dtype=np.float32)*.02
        o.stt.transcribe_wake.return_value=heard
        return o
    def test_ambient_speech_never_reaches_cloud_memory_or_tools(self):
        o=self.orch('Conversa ambiente sem ativação')
        with patch('core.orchestrator.registry.call') as tool:o.run_forever()
        o.llm.chat_stream.assert_not_called();o.memory.log.assert_not_called()
        o.speaker.score.assert_not_called();tool.assert_not_called()
        self.assertEqual(o.state,'sleeping')
    def test_name_and_request_reuses_transcript_keeps_biometrics(self):
        o=self.orch('Ei Viv, explique as estrelas')
        with patch('core.orchestrator.try_fast_path',return_value=None):o.run_forever()
        o.llm.chat_stream.assert_called_once();o.speaker.score.assert_called_once()
        o.stt.transcribe.assert_not_called()
        self.assertIn('explique as estrelas',str(o.llm.chat_stream.call_args))
    def test_name_alone_opens_second_capture(self):
        o=self.orch('Viv');o.stt.transcribe.return_value='Explique as estrelas'
        with patch('core.orchestrator.try_fast_path',return_value=None):o.run_forever()
        self.assertEqual(o.audio.record_utterance.call_count,2)
        o.llm.chat_stream.assert_called_once();o.speaker.score.assert_called_once()
    def test_wake_does_not_authorize_privileged_actions(self):
        o=self.orch('Viv, pedido simulado');o.speaker.is_owner.return_value=False
        o.llm.chat_stream.side_effect=[iter([('tool',{'name':'system.power','args':{}})]),iter([('token','Recusado')])]
        with patch('core.orchestrator.try_fast_path',return_value=None),patch('core.orchestrator.registry.call') as tool:o.run_forever()
        tool.assert_not_called()

    def test_pending_name_does_not_block_clap_activation(self):
        from concurrent.futures import Future
        o=self.orch('unused');o._wake_future=Future()
        o.audio.frames.return_value=iter([bytes(640)])
        o.audio.clap_triggered.return_value=True
        o.stt.transcribe.return_value='Explique as estrelas'
        with patch('core.orchestrator.try_fast_path',return_value=None):o.run_forever()
        o.llm.chat_stream.assert_called_once()
        self.assertTrue(o._wake_discard)
if __name__=='__main__':unittest.main(verbosity=2)
