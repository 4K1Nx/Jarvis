import unittest
from unittest.mock import Mock, patch
from scripts import test_conversation as base
from core.model_selection import ModelSelection, CANDIDATES
from core.llm import LLM

class SelectionTests(unittest.TestCase):
    def llm(self):
        obj=LLM.__new__(LLM)
        obj.c={'model':'gemini-3.8-flash'};obj.api_key='test-only';obj.client=Mock()
        obj.pending_model=None
        obj.available_models=Mock(return_value={'status':'ok','models':[r[0] for r in CANDIDATES]})
        return obj
    def run_selection(self,obj):
        select=ModelSelection(obj);select.lock.acquire();select._run();return select
    def response(self,code=200):
        return Mock(status_code=code,json=lambda:{'candidates':[{'content':{'parts':[{'text':'OK'}]}}]})
    def test_cheapest_success_stops_and_only_applies_on_next_turn(self):
        obj=self.llm();obj.client.post.return_value=self.response()
        result=self.run_selection(obj)
        self.assertEqual(obj.client.post.call_count,1)
        self.assertEqual(result.report['selected'],CANDIDATES[0][0])
        self.assertEqual(obj.c['model'],'gemini-3.8-flash')
        obj.activate_selected_model()
        self.assertEqual(obj.c['model'],CANDIDATES[0][0])
        body=obj.client.post.call_args.kwargs['json']
        self.assertNotIn('tools',body);self.assertNotIn('systemInstruction',body)
    def test_retired_then_timeout_then_success(self):
        obj=self.llm();obj.client.post.side_effect=[self.response(404),TimeoutError('private'),self.response()]
        report=self.run_selection(obj).report
        self.assertEqual(report['selected'],CANDIDATES[2][0])
        self.assertEqual(obj.client.post.call_count,3)
        self.assertNotIn('private',str(report))
    def test_all_fail_preserves_config(self):
        obj=self.llm();obj.client.post.return_value=self.response(503)
        report=self.run_selection(obj).report
        self.assertIsNone(report['selected']);self.assertIsNone(obj.pending_model)
        self.assertEqual(obj.client.post.call_count,len(CANDIDATES))
        self.assertEqual(obj.c['model'],'gemini-3.8-flash')
    def test_missing_catalog_never_probes(self):
        obj=self.llm();obj.available_models.return_value={'status':'unavailable'}
        self.run_selection(obj);obj.client.post.assert_not_called()
    def test_no_duplicate_worker(self):
        select=ModelSelection(self.llm());select.lock.acquire()
        with patch('core.model_selection.threading.Thread') as worker:
            self.assertFalse(select.start());worker.assert_not_called()
        select.lock.release()
    def test_api_returns_report_and_starts_without_waiting(self):
        import server
        selection=Mock(report={'status':'testing','selected':None,'rows':[]})
        selection.start.return_value=True
        with patch.object(server,'SELECTION',selection):
            self.assertTrue(server.select_model()['started'])
            self.assertEqual(server.model_selection_status()['status'],'testing')

if __name__=='__main__':unittest.main()
