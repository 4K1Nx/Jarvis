"""Public, bounded relevance probe. No dotenv, Gemini credentials, microphone or OS tools."""
from pathlib import Path
import sys,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import Research
from core.metrics import TurnTrace
trace=TurnTrace()
with trace.activate():
    r=Research('Qual era o primeiro Prime de Transformers?',[])
    report=r.run()
print(json.dumps({'status':report['status'],'attempts':report['attempts'],
                  'sources':[{'title':h['title'],'url':h['href']} for h in report['sources']],
                  'events':r.events,'timing':trace.finish()},ensure_ascii=True,indent=2))
if report['status']=='tool_error': raise SystemExit(1)
if not report['sources']: print('NO EVIDENCE: fontes insuficientes; comportamento esperado é informar a limitação, sem inventar resposta.')
