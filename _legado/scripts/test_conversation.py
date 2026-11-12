"""Offline regression checks: no microphone, network, dotenv or Windows tools."""
import asyncio
import faulthandler
faulthandler.dump_traceback_later(15, repeat=False)
import copy
import importlib
from pathlib import Path
import queue
import sys
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import yaml

# These modules must never initialize their real services during this suite.
sys.modules['tools.system'] = types.ModuleType('tools.system')
sys.modules['dotenv'] = types.SimpleNamespace(load_dotenv=lambda: None)
from core.orchestrator import Orchestrator, is_confirmation
from core.audio_in import AudioInput
from core.speaker_id import SpeakerID
from core.bus import EventBus
from core.llm import LLM
from core.tts import TTS

CFG = yaml.safe_load((Path(__file__).resolve().parents[1] / 'config.yaml').read_text(encoding='utf-8'))


class ConversationTests(unittest.TestCase):
    def make_orch(self):
        llm = Mock()
        llm.chat_stream.side_effect = lambda *a, **k: iter([('token', 'Entendi, vamos conversar.')])
        tts = Mock()
        tts.stream_sentences.side_effect = lambda tokens, stop=None: ''.join(tokens)
        memory = Mock()
        memory.block_text.return_value = ''
        speaker = Mock(owner='Pessoa', last_score=0.9, threshold=0.75)
        speaker.is_owner.return_value = True
        cfg=copy.deepcopy(CFG);cfg["assistant"]["local_mode"]=False
        return Orchestrator(cfg, Mock(), Mock(), Mock(), llm, tts, memory, speaker)

    def test_context_and_identity(self):
        o = self.make_orch()
        o.handle('Meu projeto chama Aurora.', time.perf_counter())
        o.handle('Como se chama meu projeto?', time.perf_counter())
        msgs = o.llm.chat_stream.call_args.args[0]
        self.assertEqual(msgs[1]['content'], 'Meu projeto chama Aurora.')
        self.assertEqual(msgs[2]['role'], 'assistant')
        self.assertIn('You are Viv, Pessoa', msgs[0]['content'])
        self.assertIn('Brazilian Portuguese', msgs[0]['content'])

    def test_fast_answer_is_in_context(self):
        o = self.make_orch()
        with patch('core.orchestrator.try_fast_path', return_value='Agora são dez horas.'):
            o.handle('Que horas são?', time.perf_counter())
        o.handle('Repita a resposta anterior.', time.perf_counter())
        self.assertEqual(o.llm.chat_stream.call_args.args[0][2]['content'], 'Agora são dez horas.')

    def test_history_is_bounded(self):
        o = self.make_orch()
        o.cfg['assistant']['history_turns'] = 2
        for i in range(10):
            o.handle(f'Pergunta {i}', time.perf_counter())
        self.assertLessEqual(len(o.history), 6)

    def test_confirmation_stays_visible_during_prompt_playback(self):
        o = self.make_orch()
        o.pending = {'name': 'simulation', 'args': {}}
        o.state = 'confirm'
        o.tts.on_playback()
        self.assertEqual(o.state, 'confirm')

    def test_confirmation_does_not_accept_negative(self):
        for phrase in ['não confirmo', 'não', 'não pode fazer', 'sim, mas não agora', 'não, sim']:
            self.assertFalse(is_confirmation(phrase))
        for phrase in ['Sim.', 'Confirmo!', 'Pode fazer.']:
            self.assertTrue(is_confirmation(phrase))

    def test_missing_biometrics_never_authorizes(self):
        sp = SpeakerID({'speaker_id': {'enabled': False}})
        self.assertFalse(sp.is_owner(privileged=True))
        self.assertEqual(sp.score(np.zeros(320)), 0)
        sp.enabled = True
        self.assertFalse(sp.is_owner())

    def test_privileged_tool_blocked(self):
        o = self.make_orch()
        o.speaker.is_owner.return_value = False
        o.llm.chat_stream.side_effect = [iter([('tool', {'name': 'system.power', 'args': {}})]), iter([('token', 'Acesso recusado.')])]
        with patch('core.orchestrator.registry.call') as call:
            o.handle('Pedido simulado', time.perf_counter())
        call.assert_not_called()

    def test_destructive_tool_requires_confirmation(self):
        o = self.make_orch()
        o.llm.chat_stream.side_effect = [iter([('tool', {'name': 'system.power', 'args': {}})]), iter([('token', 'Cancelado.')])]
        with patch.object(o, '_await_confirmation', return_value=False) as confirm, patch('core.orchestrator.registry.call') as call:
            o.handle('Pedido simulado', time.perf_counter())
        confirm.assert_called_once()
        call.assert_not_called()

    def test_double_clap_and_queue_flush(self):
        with patch('core.audio_in.VAD'):
            audio = AudioInput(CFG)
        pulse = (np.tile([12000, -12000], 160).astype(np.int16)).tobytes()
        with patch('core.audio_in.time.monotonic', side_effect=[10, 10.1, 10.25, 10.3]):
            self.assertFalse(audio.clap_triggered(pulse))
            self.assertFalse(audio.clap_triggered(bytes(640)))
            self.assertTrue(audio.clap_triggered(pulse))
            self.assertFalse(audio.clap_triggered(pulse))
        audio.q.put(pulse)
        audio.discard_pending()
        self.assertTrue(audio.q.empty())

    def test_manual_hud_wake(self):
        o = self.make_orch()
        o.wake_now()
        self.assertTrue(o.consume_manual_wake())
        self.assertFalse(o.consume_manual_wake())

    def test_stt_model_loaded_once(self):
        model = Mock()
        model.transcribe.side_effect = lambda *a, **k: (iter([types.SimpleNamespace(text=' Olá Viv')]), None)
        factory = Mock(return_value=model)
        with patch.dict(sys.modules, {'faster_whisper': types.SimpleNamespace(WhisperModel=factory)}):
            sys.modules.pop('core.stt', None)
            STT = importlib.import_module('core.stt').STT
            stt = STT(CFG)
            for _ in range(3):
                self.assertEqual(stt.transcribe(np.zeros(16000, dtype=np.float32)), 'Olá Viv')
        factory.assert_called_once_with('small', device='cpu', compute_type='int8', local_files_only=True)
        self.assertEqual(model.transcribe.call_args.kwargs['language'], 'pt')

    def test_gemini_history_mapping(self):
        llm = LLM.__new__(LLM)
        result = llm._gemini_contents([{'role': 'user', 'content': 'Aurora'}, {'role': 'assistant', 'content': 'Entendi.'}, {'role': 'user', 'content': 'Qual nome?'}])
        self.assertEqual([r['role'] for r in result], ['user', 'model', 'user'])

    def test_edge_voice_and_playback(self):
        async def chunks():
            yield {'type': 'audio', 'data': b'mocked audio'}
        speech = Mock()
        speech.stream = chunks
        edge = types.SimpleNamespace(Communicate=Mock(return_value=speech))
        sf = types.SimpleNamespace(read=Mock(return_value=(np.zeros(100, dtype=np.float32), 24000)))
        with patch.dict(sys.modules, {'edge_tts': edge, 'soundfile': sf}), patch('core.tts.sd.OutputStream') as output:
            tts = TTS(CFG)
            self.assertEqual(tts.stream_sentences(iter(['Olá. ', 'Tudo bem?'])), 'Olá. Tudo bem?')
        self.assertEqual(output.call_count, 1)
        output.return_value.write.assert_called_once()
        self.assertEqual(edge.Communicate.call_args.args[1], 'pt-BR-FranciscaNeural')

    def test_turn_recovers_after_stt_failure(self):
        o = self.make_orch()
        o.audio.frames.return_value = iter([b'frame'])
        o.audio.level.return_value = 0.0
        o.stt.transcribe.side_effect = RuntimeError('simulated failure')
        o.run_forever()
        self.assertEqual(o.state, 'error')
        o.audio.discard_pending.assert_called_once()

    def test_hud_cross_thread_delivery(self):
        async def check():
            bus = EventBus()
            q = bus.subscribe()
            worker = threading.Thread(target=lambda: bus.emit('state', 'listening'))
            worker.start()
            event = await asyncio.wait_for(q.get(), timeout=1)
            worker.join()
            bus.unsubscribe(q)
            self.assertEqual(event['text'], 'listening')
        asyncio.run(check())


class Viv11Tests(unittest.TestCase):
    def test_search_profile_and_tls(self):
        from core.web_search import VivSearch
        with patch('duckduckgo_search.duckduckgo_search.primp.Client') as client:
            VivSearch(verify=True)
        self.assertEqual(client.call_args.kwargs['impersonate'], 'chrome_146')
        self.assertIs(client.call_args.kwargs['verify'], True)

    def test_search_fallback(self):
        from core.web_search import search
        with patch('core.web_search.VivSearch', side_effect=RuntimeError('rate limit')), patch('core.web_search._rss_search', return_value=[{'title': 'Python', 'href': 'https://python.org'}]) as fallback:
            self.assertEqual(len(search('public query')), 1)
        fallback.assert_called_once_with('public query', 4)

    def test_search_primary_preserved(self):
        from core.web_search import search
        with patch('core.web_search.VivSearch') as factory, patch('core.web_search._rss_search') as fallback:
            factory.return_value.__enter__.return_value.text.return_value = [{'title': 'Python', 'href': 'https://python.org', 'body': 'Language'}]
            hits = search('public query')
            self.assertEqual(hits[0]['provider'], 'duckduckgo')
        fallback.assert_not_called()

    def test_metrics_accumulate_and_do_not_contain_content(self):
        import tempfile
        import json
        from core.metrics import Metrics, TurnTrace, measure
        trace = TurnTrace(start=0)
        with trace.activate(), patch('core.metrics.time.perf_counter', side_effect=[1, 1.2, 2, 2.3]):
            with measure('gemini_ms'):
                pass
            with measure('gemini_ms'):
                pass
        self.assertAlmostEqual(trace.data['gemini_ms'], 500)
        self.assertEqual(trace.data['gemini_calls'], 2)
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'latency.jsonl')
            metrics = Metrics({'metrics': {'log_path': path}})
            metrics.record(dict(trace.data, utterance='PRIVATE', api_key='SECRET', error='SENSITIVE'))
            data = Path(path).read_text()
            for forbidden in ['PRIVATE', 'SECRET', 'SENSITIVE', 'utterance', 'api_key']:
                self.assertNotIn(forbidden, data)
            self.assertIn('gemini_ms', json.loads(data))

    def test_first_playback_is_not_end_of_audio(self):
        from core.metrics import TurnTrace, playback_started
        trace = TurnTrace(start=1)
        trace.capture_end = 2
        with trace.activate(), patch('core.metrics.time.perf_counter', side_effect=[3, 9, 10]):
            playback_started()
            playback_started()
            data = trace.finish()
        self.assertEqual(data['playback_start_ms'], 2000)
        self.assertEqual(data['response_start_ms'], 1000)
        self.assertEqual(data['total_ms'], 9000)

    def test_failed_stage_is_measured(self):
        from core.metrics import TurnTrace, measure
        trace = TurnTrace()
        with trace.activate():
            with self.assertRaises(RuntimeError):
                with measure('search_ms'):
                    raise RuntimeError('simulated')
        self.assertIn('search_ms', trace.data)
        self.assertNotIn('simulated', str(trace.data))


    def test_status_endpoint_is_content_free(self):
        import importlib
        from fastapi.testclient import TestClient
        with patch('core.audit.Audit'):
            server = importlib.import_module('server')
        previous = server.ORCH['ref']
        server.ORCH['ref'] = None
        try:
            with TestClient(server.app) as client:
                response = client.get('/api/status')
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data['gemini']['status'], 'unverified')
                self.assertEqual(data['tts']['voice'], 'pt-BR-FranciscaNeural')
                for key in ('api_key', 'GEMINI_API_KEY', 'owner', 'embedding'):
                    self.assertNotIn(key, response.text)
        finally:
            server.ORCH['ref'] = previous

    def test_rss_parsing_and_tls(self):
        from core.web_search import _rss_search
        response = Mock()
        response.content = b'<rss><channel><item><title>Python</title><link>https://python.org</link><description>Docs</description></item></channel></rss>'
        with patch('core.web_search.httpx.Client') as client:
            client.return_value.__enter__.return_value.get.return_value = response
            hits = _rss_search('public', 1)
        self.assertIs(client.call_args.kwargs['verify'], True)
        self.assertEqual(hits[0]['href'], 'https://python.org')

    def test_gemini_timed_without_playback(self):
        from core.metrics import TurnTrace
        llm = LLM.__new__(LLM)
        llm.backend = 'gemini'
        llm._gemini_once = Mock(return_value=('text', 'Olá'))
        trace = TurnTrace()
        with trace.activate():
            self.assertEqual(list(llm.chat_stream([])), [('token', 'Olá')])
        self.assertIn('gemini_ms', trace.data)
        self.assertNotIn('tts_playback_ms', trace.data)
        self.assertEqual(llm.connection_status, 'ok')

    def test_batched_tts_cancellation(self):
        tts = TTS.__new__(TTS)
        tts.cfg = {'sentence_streaming': False}
        tts.say = Mock()
        stop = threading.Event()
        def tokens():
            yield 'Primeira frase. '
            stop.set()
            yield 'Segunda frase.'
        tts.stream_sentences(tokens(), stop=stop)
        tts.say.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
