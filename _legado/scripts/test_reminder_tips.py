"""Legacy tip migration without touching real jobs or starting the scheduler."""
import sys, json, tempfile, time, unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.proactive import Proactive, LEGACY_DEMO_TEXTS

class TipTests(unittest.TestCase):
    def test_only_exact_daily_demo_messages_are_silent_and_preserved(self):
        with tempfile.TemporaryDirectory() as tmp, patch('core.proactive.threading.Thread'):
            path=Path(tmp)/'jobs.json'
            rows=[dict(at=1,text=t,repeat_daily=True) for t in LEGACY_DEMO_TEXTS for _ in range(6)]
            rows += [dict(at=1,text='My personal reminder',repeat_daily=False),dict(at=1,text='Minha rotina',repeat_daily=True)]
            path.write_text(json.dumps(rows),encoding='utf-8')
            speak=Mock();pro=Proactive({'proactive':{'jobs_path':str(path),'enabled':False}},speak)
            self.assertEqual(len(pro.pending()),2)
            pro.run_due(2)
            self.assertEqual([c.args[0] for c in speak.call_args_list],['My personal reminder','Minha rotina'])
            self.assertEqual(sum(j.text in LEGACY_DEMO_TEXTS for j in pro.jobs),12)
    def test_one_off_identical_text_is_not_silenced(self):
        with tempfile.TemporaryDirectory() as tmp, patch('core.proactive.threading.Thread'):
            speak=Mock();pro=Proactive({'proactive':{'jobs_path':str(Path(tmp)/'jobs.json')}},speak)
            pro.schedule_in(1,next(iter(LEGACY_DEMO_TEXTS)));pro.run_due(time.time()+2)
            speak.assert_called_once()
    def test_daily_registration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp, patch('core.proactive.threading.Thread'):
            pro=Proactive({'proactive':{'jobs_path':str(Path(tmp)/'jobs.json')}},Mock())
            pro.schedule_daily('08:15','Rotina pessoal');pro.schedule_daily('08:15','Rotina pessoal')
            self.assertEqual(len(pro.pending()),1)

if __name__=='__main__':unittest.main(verbosity=2)
