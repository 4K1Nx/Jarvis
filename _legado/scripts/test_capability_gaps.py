import sys,unittest,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import test_conversation as base
from core.capability_gaps import CapabilityGaps
from core.orchestrator import wake_request

class GapTests(unittest.TestCase):
    def test_persistence_dedup_and_safe_categories(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'gaps.json';report=Path(tmp)/'report.md'
            gaps=CapabilityGaps(path,report)
            gaps.record('screen_model');gaps.record('screen_model')
            gaps.record('secret-key C:/private/file.txt')
            restored=CapabilityGaps(path,report)
            self.assertEqual(restored.count(),2)
            self.assertEqual(restored.items['screen_model']['count'],2)
            self.assertNotIn('private',report.read_text(encoding='utf-8'))
            self.assertNotIn('secret',path.read_text(encoding='utf-8'))
    def test_unrecognized_local_request_records_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            o=base.ConversationTests().make_orch();o.cfg['assistant']['local_mode']=True
            o.gaps=CapabilityGaps(Path(tmp)/'gaps.json',Path(tmp)/'report.md')
            o.handle('Faça uma tarefa desconhecida',0)
            self.assertIn('command_unrecognized',o.gaps.items)
            answer=o.handle('Quais são suas pendências?',0)
            self.assertIn('Pedido não compreendido',answer)
            o.llm.chat_stream.assert_not_called()
    def test_configurable_aliases_and_brazilian_pronunciations(self):
        for text in ['Ei, Vive!','Ei Vivi','Vivi, abra a calculadora','Viv, abra a calculadora']:
            self.assertIsNotNone(wake_request(text,['Viv','Vivi','Vive']))
        self.assertEqual(wake_request('Ei, Vívie, teste',['Vívie']),'teste')
        self.assertIsNone(wake_request('eu vivi em uma cidade',['Viv','Vivi','Vive']))

if __name__=='__main__':unittest.main(verbosity=2)
