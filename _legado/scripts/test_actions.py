"""Gemini payload and process action regressions, no credentials or real PC action."""
import sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import test_conversation as safe
from core.llm import LLM,_gemini_tools,GeminiFailure
from core.process_control import matches_process,terminate_named

class ActionsTests(unittest.TestCase):
    def llm(self):
        llm=LLM.__new__(LLM);llm.backend='gemini';llm.c={'model':'gemini-2.5-flash'}
        llm.api_key='placeholder';llm.client=Mock();llm.connection_status='unverified'
        return llm
    def test_no_argument_schema_omits_empty_object(self):
        result=_gemini_tools([{'function':{'name':'system.status','parameters':{'type':'object','properties':{},'required':[]}}}])
        self.assertNotIn('parameters',result[0]['functionDeclarations'][0])
    def test_signed_tool_roundtrip(self):
        llm=self.llm()
        content={'role':'model','parts':[{'thoughtSignature':'opaque-test','functionCall':{'name':'system.kill','args':{'name':'Minecraft'},'id':'call-1'}}]}
        llm.client.post.return_value.status_code=200
        llm.client.post.return_value.json.return_value={'candidates':[{'content':content}]}
        kind,call=llm._gemini_once([{'role':'user','content':'Feche o Minecraft'}])
        self.assertEqual(kind,'tool')
        msgs=[{'role':'assistant','gemini_content':call['gemini_content']},{'role':'tool','name':'system.kill','content':'Nada executado neste teste'}]
        payload=llm._gemini_contents(msgs)
        self.assertEqual(payload[0],content)
        self.assertEqual(payload[1]['parts'][0]['functionResponse']['id'],'call-1')
    def test_http_error_is_classified_without_raw_body(self):
        llm=self.llm();llm.client.post.return_value.status_code=429
        llm.client.post.return_value.text='secret raw error'
        with self.assertRaises(GeminiFailure) as error:list(llm.chat_stream([{'role':'user','content':'teste'}]))
        self.assertEqual(str(error.exception),'quota');self.assertEqual(llm.last_error,'quota')
        self.assertNotIn('secret',str(error.exception))
    def test_java_match_is_client_specific(self):
        self.assertTrue(matches_process('Minecraft','javaw.exe',['net.minecraft.client.main.Main']))
        self.assertTrue(matches_process('Minecraft','Minecraft.Windows.exe',[]))
        self.assertFalse(matches_process('Minecraft','javaw.exe',['com.example.Editor']))
        self.assertFalse(matches_process('Minecraft','java.exe',['net.minecraft.server.Main']))
        self.assertFalse(matches_process('Mine','Minecraft.exe',[]))
        self.assertFalse(matches_process('','anything.exe',[]))
    def test_termination_is_only_simulated_and_verified(self):
        game=Mock(info={'name':'javaw.exe','cmdline':['net.minecraft.client.main.Main']})
        editor=Mock(info={'name':'javaw.exe','cmdline':['com.example.Editor']})
        result=terminate_named('Minecraft',[game,editor])
        game.terminate.assert_called_once();game.wait.assert_called_once_with(timeout=3)
        editor.terminate.assert_not_called();self.assertIn('encerrados: 1',result)
    def test_failed_termination_is_not_reported_as_success(self):
        game=Mock(info={'name':'Minecraft.exe','cmdline':[]});game.terminate.side_effect=PermissionError()
        self.assertIn('encerrados: 0',terminate_named('Minecraft',[game]))
    def test_minecraft_requires_confirmation_before_dispatch(self):
        for accepted in [False,True]:
            o=safe.ConversationTests().make_orch()
            o.llm.chat_stream.side_effect=[iter([('tool',{'name':'system.kill','args':{'name':'Minecraft'}})]),iter([('token','Resultado simulado')])]
            with patch('core.orchestrator.try_fast_path',return_value=None),patch.object(o,'_await_confirmation',return_value=accepted) as confirm,patch('core.orchestrator.registry.call',return_value='resultado simulado') as tool:
                o.handle('Feche o Minecraft',0)
                confirm.assert_called_once_with('system.kill',{'name':'Minecraft'})
                self.assertEqual(tool.call_count,int(accepted))

    def test_parallel_calls_do_not_claim_unexecuted_actions(self):
        content={'role':'model','parts':[
            {'functionCall':{'name':'system.kill','args':{},'id':'one'}},
            {'functionCall':{'name':'system.power','args':{},'id':'two'}}]}
        payload=LLM._gemini_contents([{'role':'assistant','gemini_content':content},
                                     {'role':'tool','name':'system.kill','content':'Resultado simulado'}])
        responses=payload[-1]['parts']
        self.assertEqual(len(responses),2)
        self.assertIn('Não executado',responses[1]['functionResponse']['response']['result'])
        self.assertEqual(responses[1]['functionResponse']['id'],'two')
    def test_truncated_name_request_is_discarded(self):
        from core.stt import STT
        stt=STT.__new__(STT);stt.cfg={'language':'pt'};stt.model=Mock()
        segment=Mock(text='Viv feche Minecraft mas',tokens=list(range(48)))
        stt.model.transcribe.return_value=(iter([segment]),None)
        self.assertEqual(stt.transcribe_wake([]),'')
        self.assertEqual(stt.model.transcribe.call_args.kwargs['max_new_tokens'],48)
if __name__=='__main__':unittest.main(verbosity=2)
