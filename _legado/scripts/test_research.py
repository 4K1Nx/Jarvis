"""Tests actual outbound query strings, without network, credentials or audio."""
from pathlib import Path
import sys, unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import test_conversation as conversation
from core.research import Research,queries_for


def hit(title='Prima - Transformers Wiki',body='Prima was the first Prime in Transformers.'):
    return {'title':title,'body':body,'href':'https://tfwiki.net/wiki/Prima','provider':'fixture'}


class ResearchTests(unittest.TestCase):
    def test_questions_preserve_entities_in_sent_queries(self):
        cases=[('Qual era o primeiro Prime de Transformers?',['prime','transformers'],hit()),
               ('Quem foi Prima nos Transformers?',['prima','transformers'],hit()),
               ('Quem foi o primeiro presidente do Brasil?',['presidente','brasil'],hit('Presidente do Brasil','Deodoro foi o primeiro presidente do Brasil.')),
               ('Qual a diferença entre Optimus Prime e Prima?',['optimus','prime','prima'],hit('Optimus Prime e Prima','Transformers: Optimus Prime e Prima são personagens diferentes.'))]
        for question,entities,result in cases:
            with self.subTest(question=question):
                outgoing=Mock(return_value=[result])
                research=Research(question,[],search_fn=outgoing)
                self.assertEqual(research.run('primeiro')['status'],'completed')
                actual=outgoing.call_args.args[0].lower()
                for entity in entities:self.assertIn(entity,actual)
                self.assertNotEqual(actual,'primeiro')

    def test_context_is_carried_into_actual_query(self):
        outgoing=Mock(return_value=[hit()])
        history=[{'role':'user','content':'Quem foi Prima nos Transformers?'},
                 {'role':'assistant','content':'Prima é um personagem de Transformers.'}]
        r=Research('Agora pesquisa mais sobre ele',history,search_fn=outgoing)
        r.run()
        q=outgoing.call_args.args[0].lower()
        self.assertIn('prima',q);self.assertIn('transformers',q)

    def test_pronoun_preserves_name_introduced_in_answer(self):
        outgoing=Mock(return_value=[hit()])
        history=[{'role':'user','content':'Qual era o primeiro Prime de Transformers?'},
                 {'role':'assistant','content':'Prima é apresentado como o primeiro Prime.'}]
        r=Research('Agora pesquisa mais sobre ele',history,search_fn=outgoing)
        r.run()
        self.assertIn('Prima',outgoing.call_args.args[0])
        self.assertIn('Transformers',outgoing.call_args.args[0])

    def test_irrelevant_results_reformulated_bounded(self):
        outgoing=Mock(side_effect=[[hit('Números ordinais','Primeiro segundo terceiro')],[hit()]])
        r=Research('Qual era o primeiro Prime de Transformers?',[],search_fn=outgoing)
        self.assertEqual(r.run()['status'],'completed')
        self.assertEqual(outgoing.call_count,2)
        self.assertIn('first',outgoing.call_args.args[0])
        self.assertIn('Transformers',outgoing.call_args.args[0])
        r.run();self.assertEqual(outgoing.call_count,2)
        self.assertEqual(r.events[-2:],['relevant','completed'])

    def test_failure_is_honest_and_bounded(self):
        for output,status in [( [],'no_relevant_results'),(RuntimeError('SECRET'),'tool_error')]:
            outgoing=Mock(side_effect=output if isinstance(output,Exception) else None,return_value=output)
            r=Research('Quem foi Prima nos Transformers?',[],search_fn=outgoing)
            report=r.run()
            self.assertEqual(report['status'],status)
            self.assertLessEqual(outgoing.call_count,3)
            self.assertEqual(report['sources'],[])
            self.assertNotIn('SECRET',r.evidence())

    def test_explicit_request_calls_registered_tool_before_answer(self):
        o=conversation.ConversationTests().make_orch()
        with patch('core.research.search',return_value=[hit()]) as outgoing:
            o.handle('Pesquise quem foi Prima nos Transformers',0)
        outgoing.assert_called_once()
        self.assertIn('Prima',outgoing.call_args.args[0])
        self.assertEqual(o.research.report['status'],'completed')

    def test_promise_causes_real_tool_dispatch(self):
        o=conversation.ConversationTests().make_orch()
        o.llm.chat_stream.side_effect=[iter([('token','Vou pesquisar isso para você.')]),iter([('token','Encontrei uma fonte sobre Prima.')])]
        with patch('core.research.search',return_value=[hit()]) as outgoing:
            o.handle('Quem foi Prima nos Transformers?',0)
        outgoing.assert_called_once()
        self.assertNotIn('Vou pesquisar',str(o.tts.say.call_args_list))
        self.assertEqual(o.research.report['status'],'completed')

    def test_status_events_omit_private_content(self):
        with patch('core.research.BUS.emit') as event:
            Research('Quem foi Prima nos Transformers?',[],search_fn=Mock(return_value=[])).run()
        self.assertNotIn('Quem foi',str(event.call_args_list))
        self.assertNotIn('query',str(event.call_args_list))

    def test_do_not_search_is_respected(self):
        from core.research import requires_search
        self.assertFalse(requires_search('Não pesquise, só explique.'))

    def test_empty_intent_is_not_searched(self):
        outgoing=Mock()
        report=Research('?',[],search_fn=outgoing).run()
        self.assertEqual(report['status'],'no_relevant_results')
        outgoing.assert_not_called()

    def test_generic_franchise_result_is_not_first_prime_evidence(self):
        r=Research('Qual era o primeiro Prime de Transformers?',[],search_fn=Mock(return_value=[hit('Transformers','Optimus Prime é um personagem popular de Transformers.')]))
        self.assertEqual(r.run()['status'],'no_relevant_results')

    def test_observed_stt_error_and_fillers(self):
        outgoing=Mock(return_value=[hit()])
        r=Research('pesquisa pra mim quem s\u00e3o os prime de transformas',[],search_fn=outgoing)
        self.assertEqual(r.run()['status'],'completed')
        self.assertIn('Transformers',outgoing.call_args.args[0])
        self.assertEqual([x.lower() for x in queries_for(r.question)[1]],['prime','transformers'])

    def test_observed_followup_preserves_franchise(self):
        history=[{'role':'user','content':'pesquisa pra mim quem s\u00e3o os prime de transformas'},
                 {'role':'assistant','content':'Qual universo de Transformers?'}]
        outgoing=Mock(return_value=[hit(body='Transformers: the original Primes include Prima.')])
        r=Research('universo padr\u00e3o tipo existem v\u00e1rios primes',history,search_fn=outgoing)
        self.assertEqual(r.run()['status'],'completed')
        self.assertIn('Transformers',outgoing.call_args.args[0])
        self.assertLessEqual(outgoing.call_count,3)

    def test_new_topic_does_not_inherit_franchise(self):
        history=[{'role':'user','content':'Quem foi Prima nos Transformers?'}]
        r=Research('Quem foi o primeiro presidente do Brasil?',history,search_fn=Mock(return_value=[]))
        self.assertNotIn('Transformers',r.question)

    def test_group_question_rejects_generic_optimus_page(self):
        outgoing=Mock(return_value=[hit('Transformers','Optimus Prime is a popular Transformers character.')])
        r=Research('Quem s\u00e3o os Primes de Transformers?',[],search_fn=outgoing)
        self.assertEqual(r.run()['status'],'no_relevant_results')

    def test_provider_receives_the_full_query(self):
        from core.web_search import search
        question='Qual era o primeiro Prime de Transformers?'
        with patch('core.web_search.VivSearch') as factory:
            client=factory.return_value.__enter__.return_value
            client.text.return_value=[hit()]
            search(question)
            self.assertEqual(client.text.call_args.args[0], question)

if __name__=='__main__':unittest.main(verbosity=2)
