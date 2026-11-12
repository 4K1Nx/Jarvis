import sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import test_conversation as base
from core.llm import LLM
import httpx

class VerificationTests(unittest.TestCase):
    def llm(self):
        obj=LLM.__new__(LLM);obj.c={'model':'gemini-2.5-flash'};obj.api_key='test-only'
        obj.client=Mock();obj.connection_status='error';obj.last_error='model_not_found'
        return obj
    def test_success_clears_stale_generation_error_without_claiming_generation(self):
        obj=self.llm();obj.client.get.return_value=Mock(status_code=200,json=lambda:{'supportedGenerationMethods':['generateContent']})
        with patch('core.llm.BUS.emit') as emit:
            self.assertEqual(obj.verify_connection(),'available')
            self.assertIsNone(obj.last_error)
            self.assertIsNone(emit.call_args.kwargs['error_code'])
        obj.client.post.assert_not_called()
    def test_explicit_check_tests_generation_without_memory_or_tools(self):
        obj=self.llm()
        obj.client.get.return_value=Mock(status_code=200,json=lambda:{'supportedGenerationMethods':['generateContent']})
        obj.client.post.return_value=Mock(status_code=200,json=lambda:{'candidates':[{'content':{'parts':[{'text':'OK.'}]}}]})
        self.assertEqual(obj.verify_connection(generate=True),'ok')
        body=obj.client.post.call_args.kwargs['json']
        self.assertNotIn('tools',body)
        self.assertEqual(body['contents'],[{'role':'user','parts':[{'text':'Responda apenas: OK.'}]}])

    def test_metadata_success_does_not_hide_generation_404(self):
        obj=self.llm()
        obj.client.get.return_value=Mock(status_code=200,json=lambda:{'supportedGenerationMethods':['generateContent']})
        obj.client.post.return_value=Mock(status_code=404)
        self.assertEqual(obj.verify_connection(generate=True),'error')
        self.assertEqual(obj.last_error,'model_not_found')

    def test_catalog_is_bounded_and_filters_private_or_non_generative_names(self):
        obj=self.llm()
        obj.client.get.return_value=Mock(status_code=200,json=lambda:{'models':[
            {'name':'models/gemini-2.5-flash','supportedGenerationMethods':['generateContent']},
            {'name':'private-project/secret','supportedGenerationMethods':['generateContent']},
            {'name':'models/gemini-embed','supportedGenerationMethods':['embedContent']}],
            'nextPageToken':'private-page-token'})
        result=obj.available_models()
        self.assertEqual(result['models'],['gemini-2.5-flash'])
        self.assertFalse(result['complete'])
        self.assertEqual(obj.client.get.call_count,3)
        self.assertNotIn('private',str(result))

    def test_error_diagnostics_never_return_raw_provider_message(self):
        obj=self.llm()
        response=Mock(status_code=404,json=lambda:{'error':{'status':'NOT_FOUND',
            'message':'private-key private-project model not found for API version v1beta'}})
        result=obj.safe_error(response)
        self.assertEqual(result['reason'],'model_or_api_version')
        self.assertEqual(result['api_status'],'NOT_FOUND')
        self.assertNotIn('private',str(result))

    def test_stable_probe_uses_same_model_without_mutation(self):
        obj=self.llm()
        obj.client.post.return_value=Mock(status_code=200,json=lambda:{'candidates':[{'content':{'parts':[{'text':'OK'}]}}]})
        result=obj.probe_stable_generation()
        self.assertTrue(result['answered'])
        self.assertIn('/v1/models/gemini-2.5-flash:generateContent',obj.client.post.call_args.args[0])
        self.assertEqual(obj.c,{'model':'gemini-2.5-flash'})
        self.assertNotIn('tools',obj.client.post.call_args.kwargs['json'])

    def test_transient_503_recovers_and_keeps_model(self):
        obj=self.llm();obj.c['model']='gemini-3.8-flash'
        obj.client.post.side_effect=[Mock(status_code=503),Mock(status_code=200,
            json=lambda:{'candidates':[{'content':{'parts':[{'text':'OK'}]}}]})]
        with patch('core.llm.time.sleep') as sleep:
            self.assertEqual(obj._gemini_once([{'role':'user','content':'Oi'}]),('text','OK'))
        self.assertEqual(obj.client.post.call_count,2)
        sleep.assert_called_once_with(1)
        self.assertEqual(obj.diagnostic['attempts'],2)
        body=obj.client.post.call_args.kwargs['json']
        self.assertNotIn('temperature',body['generationConfig'])
        self.assertIn('gemini-3.8-flash',obj.client.post.call_args.args[0])

    def test_persistent_503_stops_after_three_attempts(self):
        from core.llm import GeminiFailure
        obj=self.llm();obj.client.post.return_value=Mock(status_code=503,json=lambda:{'error':{'status':'UNAVAILABLE'}})
        with patch('core.llm.time.sleep') as sleep:
            with self.assertRaises(GeminiFailure):obj._gemini_once([{'role':'user','content':'Oi'}])
        self.assertEqual(obj.client.post.call_count,3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list],[1,2])
        self.assertEqual(obj.diagnostic['http_status'],503)

    def test_permanent_errors_are_not_retried(self):
        from core.llm import GeminiFailure
        for code in (400,401,403,404,429):
            obj=self.llm();obj.client.post.return_value=Mock(status_code=code,json=lambda:{})
            with patch('core.llm.time.sleep') as sleep:
                with self.assertRaises(GeminiFailure):obj._gemini_once([{'role':'user','content':'Oi'}])
            obj.client.post.assert_called_once();sleep.assert_not_called()

    def test_tool_response_is_yielded_only_once_after_retry(self):
        obj=self.llm();obj.backend='gemini'
        obj.client.post.side_effect=[Mock(status_code=503),Mock(status_code=200,
            json=lambda:{'candidates':[{'content':{'parts':[{'functionCall':{'name':'web.search','args':{'query':'astronomia'}}}]}}]})]
        with patch('core.llm.time.sleep'):
            result=list(obj.chat_stream([{'role':'user','content':'Pesquise astronomia'}]))
        self.assertEqual(len(result),1)
        self.assertEqual(result[0][0],'tool')
        self.assertEqual(result[0][1]['name'],'web.search')
        self.assertEqual(obj.client.post.call_count,2)

    def test_http_errors_are_distinct(self):
        for status,code in [(401,'authentication'),(403,'permission'),(404,'model_not_found'),(429,'quota'),(503,'server_error')]:
            obj=self.llm();obj.client.get.return_value=Mock(status_code=status)
            self.assertEqual(obj.verify_connection(),'error');self.assertEqual(obj.last_error,code)
    def test_timeout_does_not_leak_exception(self):
        obj=self.llm();obj.client.get.side_effect=httpx.ReadTimeout('private details')
        self.assertEqual(obj.verify_connection(),'error');self.assertEqual(obj.last_error,'timeout')
    def test_missing_key_never_calls_api(self):
        obj=self.llm();obj.api_key='';obj.verify_connection()
        obj.client.get.assert_not_called();self.assertEqual(obj.last_error,'authentication')

if __name__=='__main__':unittest.main(verbosity=2)
