"""Public search probe; no dotenv, credentials, microphone or OS tools."""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.web_search import search
from core.metrics import TurnTrace

if __name__ == '__main__':
    trace = TurnTrace()
    with trace.activate():
        hits = search('Python programming language official documentation', max_results=3)
    if not hits or not all(h.get('title') and h.get('href', '').startswith('http') for h in hits):
        raise SystemExit('FAIL: pesquisa não retornou resultados válidos')
    print(json.dumps({'count': len(hits), 'providers': sorted({h['provider'] for h in hits}), 'urls': [h['href'] for h in hits],
                      'timings': trace.finish()}, indent=2))
