"""Bounded public probes, economical first. Never executes tools or writes config."""
import threading
import time

# USD / million text tokens, standard tier, checked 2026-10-16.
# https://ai.google.dev/gemini-api/docs/pricing
CANDIDATES = (
    ('gemini-2.5-flash-lite', .10, .40),
    ('gemini-3.1-flash-lite', .25, 1.50),
    ('gemini-2.5-flash', .30, 2.50),
    ('gemini-3-flash-preview', .50, 3.00),
    ('gemini-3.8-flash', .75, 3.75),
)

class ModelSelection:
    def __init__(self, llm):
        self.llm = llm
        self.lock = threading.Lock()
        self.report = {'status':'idle', 'selected':None, 'rows':self.rows()}

    @staticmethod
    def rows():
        return [dict(model=m, input_price=i, output_price=o, status='pending') for m,i,o in CANDIDATES]

    def start(self):
        if not self.lock.acquire(blocking=False):
            return False
        self.report = {'status':'testing', 'selected':None, 'rows':self.rows()}
        threading.Thread(target=self._run, daemon=True, name='viv-model-selection').start()
        return True

    def _run(self):
        rows = self.rows()
        selected = None
        status = 'unavailable'
        deadline = time.monotonic() + 60
        def publish(current):
            self.report = {'status':current, 'selected':selected, 'rows':[dict(r) for r in rows]}
        try:
            catalog = self.llm.available_models()
            if catalog.get('status') != 'ok':
                status = 'catalog_unavailable'
                return
            for row in rows:
                if time.monotonic() >= deadline:
                    status = 'timeout'
                    break
                if row['model'] not in catalog['models']:
                    row['status'] = 'not_listed'
                    publish('testing')
                    continue
                row['status'] = 'testing'
                publish('testing')
                started = time.monotonic()
                try:
                    response = self.llm.client.post(
                        'https://generativelanguage.googleapis.com/v1beta/models/'+row['model']+':generateContent',
                        headers={'x-goog-api-key':self.llm.api_key},
                        timeout=max(.1,min(8,deadline-time.monotonic())),
                        json={'contents':[{'role':'user','parts':[{'text':'Responda apenas: OK.'}]}],
                              'generationConfig':{'maxOutputTokens':1024, **({'thinkingConfig':{'thinkingLevel':'low'}} if row['model'].startswith('gemini-3') else {})}})
                    row['http_status'] = response.status_code
                    if response.status_code == 200:
                        parts = [p for c in response.json().get('candidates', [])
                                 for p in c.get('content', {}).get('parts', [])]
                        answered = any(isinstance(p.get('text'), str) and p['text'].strip()
                                       and not p.get('thought') for p in parts)
                        row['status'] = 'ok' if answered else 'empty'
                    else:
                        row['status'] = 'failed'
                    if row['status'] == 'ok':
                        selected = row['model']
                        # Applied only at the start of a conversation turn.
                        self.llm.pending_model = selected
                        status = 'selected'
                        break
                    if response.status_code in (401,403):
                        status = 'access_denied'
                        break
                except Exception:
                    row['status'] = 'timeout_or_connection'
                finally:
                    row['duration_ms'] = round((time.monotonic()-started)*1000)
                    publish('testing')
        finally:
            publish(status)
            self.lock.release()
