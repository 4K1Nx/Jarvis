"""Local mode tests: mock all PC/network actions; temp files only."""
import sys,unittest,tempfile,time
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import test_conversation as base
from core.local_commands import parse
from core.proactive import Proactive
from core.text_files import append_text

class LocalTests(unittest.TestCase):
    def orch(self):
        o=base.ConversationTests().make_orch();o.cfg['assistant']['local_mode']=True
        return o
    def test_explicit_commands_preserve_entities(self):
        self.assertEqual(parse('Pesquise sobre Optimus Prime')['args']['query'],'Optimus Prime')
        self.assertEqual(parse('Me lembre em cinco minutos de beber água')['args'],{'minutes':5,'text':'beber água'})
        self.assertEqual(parse('Abra a calculadora'),{'tool':'desktop.open_calculator','args':{}})
        self.assertEqual(parse('Feche o Minecraft pra mim, por favor')['args']['name'],'Minecraft')
    def test_unsupported_and_negated_text_never_dispatches(self):
        for text in ['Não feche Minecraft','Será que você consegue apagar arquivos?', 'Abra a calculadora e apague arquivos']:
            self.assertNotIn('tool',parse(text))
    def test_simple_reply_does_not_use_gemini(self):
        o=self.orch();answer=o.handle('Ei, vive, tá me ouvindo?',time.perf_counter())
        self.assertIn('ouvi',answer);o.llm.chat_stream.assert_not_called()
    def test_local_tool_owner_gate(self):
        o=self.orch();o.speaker.is_owner.return_value=False
        with patch('core.orchestrator.registry.call') as call:
            self.assertIn('não foi verificada',o.handle('Abra o bloco de notas',0));call.assert_not_called()
    def test_file_edit_requires_confirmation(self):
        o=self.orch()
        with patch.object(o,'_await_confirmation',return_value=False) as confirm,patch('core.orchestrator.registry.call') as call:
            o.handle('Acrescente "nota" ao arquivo "C:\\Temp\\notes.txt"',0)
            confirm.assert_called_once();call.assert_not_called()
        o.llm.chat_stream.assert_not_called()
    def test_local_reminder_uses_registered_tool_without_gemini(self):
        o=self.orch()
        with patch('core.orchestrator.registry.call',return_value='Lembrete criado') as call:
            o.handle('Me lembre em 5 minutos de beber água',0)
            self.assertEqual(call.call_args.args[:2],('reminder.set',{'minutes':5,'text':'beber água'}))
        o.llm.chat_stream.assert_not_called()
    def test_search_without_gemini_preserves_real_sources(self):
        o=self.orch()
        def search(name,args,ctx):
            self.assertEqual(name,'web.search');self.assertEqual(args['query'],'Optimus Prime')
            ctx['orchestrator'].research.report={'sources':[{'title':'Optimus Prime','href':'https://example.org/prime'}],'status':'completed'}
            return 'resultado simulado'
        with patch('core.orchestrator.registry.call',side_effect=search):
            answer=o.handle('Pesquise sobre Optimus Prime',0)
        self.assertIn('Primeiro título: Optimus Prime',answer)
        o.llm.chat_stream.assert_not_called();o.llm.plan_search.assert_not_called()
    def test_transcription_test_never_calls_memory_or_tools(self):
        o=self.orch();o.transcription_only=True
        o.audio.frames.return_value=iter([bytes(640)])
        o.audio.record_utterance.return_value=np.ones(16000,dtype=np.float32)*.01
        o.stt.transcribe.return_value='Feche Minecraft'
        with patch('core.orchestrator.registry.call') as call:o.run_forever();call.assert_not_called()
        o.llm.chat_stream.assert_not_called();o.memory.log.assert_not_called();o.speaker.score.assert_not_called()
    def test_reminder_persists_and_fires_once(self):
        with tempfile.TemporaryDirectory() as tmp,patch('core.proactive.threading.Thread'):
            cfg={'proactive':{'jobs_path':str(Path(tmp)/'jobs.json')}}
            pro=Proactive(cfg,Mock());pro.schedule_in(60,'Água')
            restored=Proactive(cfg,Mock());self.assertEqual(len(restored.pending()),1)
            restored.run_due(time.time()+61);restored.run_due(time.time()+62)
            restored.speak.assert_called_once_with('Água');self.assertEqual(restored.pending(),[])
    def test_failed_reminder_stays_pending(self):
        with tempfile.TemporaryDirectory() as tmp,patch('core.proactive.threading.Thread'):
            pro=Proactive({'proactive':{'jobs_path':str(Path(tmp)/'jobs.json')}},Mock(side_effect=RuntimeError()))
            pro.schedule_in(1,'Teste');pro.run_due(time.time()+2)
            self.assertEqual(len(pro.pending()),1)
    def test_append_preserves_existing_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'notes.txt';target.write_text('Anterior',encoding='utf-8')
            self.assertIn('preservado',append_text(str(target),'Novo'))
            self.assertEqual(target.read_text(encoding='utf-8'),'Anterior\nNovo\n')
            self.assertIn('apenas',append_text(str(Path(tmp)/'blocked.exe'),'x'))
    def test_screen_and_optimization_do_not_promise_unavailable_actions(self):
        self.assertEqual(parse('Observe minha tela')['tool'],'vision.read_screen_local')
        self.assertEqual(parse('Otimize meu PC')['tool'],'system.diagnose')

if __name__=='__main__':unittest.main(verbosity=2)
