"""No real desktop access, microphone, network or personal files."""
import sys, tempfile, unittest, subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import test_conversation as base
from core.text_files import operate
from core.local_commands import parse
from core.screen_access import read_active_window
from core.pc_diagnostics import diagnose

class Capabilities(unittest.TestCase):
    def test_create_read_replace_backup_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'sample.txt'
            self.assertIn('criado',operate(str(p),'create','Olá mundo'))
            self.assertIn('Não foi possível',operate(str(p),'create','apagado'))
            self.assertEqual(operate(str(p),'read'),'Olá mundo')
            self.assertIn('substituído',operate(str(p),'replace','Viv','mundo'))
            self.assertEqual(p.read_text(encoding='utf-8'),'Olá Viv')
            backup=list(p.parent.glob('*.viv-backup-*'))
            self.assertEqual(len(backup),1)
            self.assertEqual(backup[0].read_text(encoding='utf-8'),'Olá mundo')
    def test_reject_ambiguous_and_hidden_without_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'sample.txt';p.write_text('a a',encoding='utf-8')
            self.assertIn('exatamente uma',operate(str(p),'replace','b','a'))
            self.assertEqual(p.read_text(),'a a')
            with patch.object(Path,'read_text',side_effect=AssertionError('must not read')):
                self.assertIn('apenas',operate(str(Path(tmp)/'.env'),'read'))
                self.assertIn('absoluto',operate('relative.txt','read'))
    def test_parsing_preserves_exact_arguments(self):
        self.assertEqual(parse('Substitua "antigo" por "novo" no arquivo "C:\Temp\nota.txt"')['args'],
                         {'path':'C:\Temp\nota.txt','old':'antigo','text':'novo'})
        self.assertEqual(parse('Crie o arquivo "C:\Temp\nota.txt" com texto "Olá"')['tool'],'files.create_text')
        self.assertNotIn('tool',parse('Não leia minha tela'))
    def test_screen_mock_and_timeout_no_raw_error(self):
        with patch('core.screen_access.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='{"texts":["Janela de teste"]}')) as run:
            self.assertIn('Janela de teste',read_active_window())
            self.assertNotIn('shell',run.call_args.kwargs)
            self.assertEqual(run.call_args.kwargs['timeout'],8)
        with patch('core.screen_access.subprocess.run',side_effect=subprocess.TimeoutExpired('private',8)):
            result=read_active_window();self.assertIn('indisponível',result);self.assertNotIn('private',result)
    def test_diagnostic_mock(self):
        with patch('core.pc_diagnostics.psutil.virtual_memory',return_value=SimpleNamespace(percent=92)),patch('core.pc_diagnostics.psutil.disk_usage',return_value=SimpleNamespace(percent=95)),patch('core.pc_diagnostics.psutil.process_iter',return_value=[SimpleNamespace(info={'name':'Teste','memory_info':SimpleNamespace(rss=1048576)})]):
            result=diagnose();self.assertIn('Teste: 1 MB',result);self.assertIn('RAM elevada',result);self.assertIn('Nenhuma configuração',result)
    def orch(self):
        o=base.ConversationTests().make_orch();o.cfg['assistant']['local_mode']=True;return o
    def test_new_mutations_require_confirmation(self):
        o=self.orch()
        with patch.object(o,'_await_confirmation',return_value=False) as confirm,patch('core.orchestrator.registry.call') as call:
            o.handle('Crie o arquivo "C:\Temp\nota.txt" com texto "Olá"',0)
            confirm.assert_called_once();call.assert_not_called()
    def test_screen_owner_and_content_privacy(self):
        o=self.orch();o.speaker.is_owner.return_value=False
        with patch('core.orchestrator.registry.call') as call:
            o.handle('Leia minha tela',0);call.assert_not_called()
        o=self.orch()
        with patch('core.orchestrator.registry.call',return_value='PRIVATE SCREEN TEXT'):
            self.assertIn('PRIVATE SCREEN TEXT',o.handle('Leia minha tela',0))
        self.assertNotIn('PRIVATE SCREEN TEXT',str(o.memory.log.call_args_list))
        self.assertNotIn('PRIVATE SCREEN TEXT',str(o.history))
        self.assertNotIn('PRIVATE SCREEN TEXT',str(o.tts.say.call_args_list))
        o.llm.chat_stream.assert_not_called()

if __name__=='__main__':unittest.main(verbosity=2)
