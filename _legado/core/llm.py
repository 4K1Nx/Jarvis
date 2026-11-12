"""Gemini API brain for Viv.

Microphone capture, STT, memory and tool execution stay local. Edge TTS sends response text to its online service.
Only the reasoning request and the text/context sent to Gemini leave the laptop.
"""
import json, os, httpx, re, time
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
from core.bus import BUS
from core.metrics import measure


def _clean_schema(props):
    out = {}
    for name, spec in (props or {}).items():
        s = dict(spec)
        s.pop("required", None)
        out[name] = s
    return out


def _gemini_tools(tools):
    declarations = []
    for t in tools or []:
        fn = t.get("function", {})
        params = fn.get("parameters", {"type": "object", "properties": {}})
        declaration = {
            "name": fn.get("name"),
            "description": fn.get("description", ""),
            "parameters": {
                "type": "object",
                "properties": _clean_schema(params.get("properties", {})),
                "required": params.get("required", []),
            },
        }
        if not params.get('properties'):
            declaration.pop('parameters')
        declarations.append(declaration)
    return [{"functionDeclarations": declarations}] if declarations else []


class GeminiFailure(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class LLM:
    def __init__(self, cfg: dict):
        self.c = dict(cfg["llm"])
        self.pending_model = None
        self.connection_status = "unverified"
        self.last_error = None
        self.diagnostic = {}
        self.backend = self.c.get("backend", "gemini").lower()
        self.client = httpx.Client(timeout=self.c.get("timeout_seconds", 90))
        self.api_key = os.getenv(self.c.get("api_key_env", "GEMINI_API_KEY"), "").strip()
        if self.backend == "gemini" and not self.api_key and not cfg.get("assistant",{}).get("local_mode",False):
            raise RuntimeError(
                f"Chave Gemini ausente: {self.c.get('api_key_env', 'GEMINI_API_KEY')}. "
                "Configure a variavel no PowerShell que inicia a Viv. Nao envie a chave no chat."
            )

    def activate_selected_model(self):
        model = getattr(self, 'pending_model', None)
        if model:
            self.c = {**self.c, 'model':model}
            self.pending_model = None
            self.connection_status = 'available'
            self.last_error = None
            self.diagnostic = {'phase':'session_selection'}
            BUS.emit('service', '', service='gemini', status='available', model=model)

    def verify_connection(self, generate=False):
        """Metadata at startup; optional public generation probe from the HUD button."""
        self.connection_status = 'checking'
        self.last_error = None
        self.diagnostic = {'phase': 'metadata', 'http_status': None}
        BUS.emit('service', '', service='gemini', status='checking', error_code=None)
        try:
            if not self.api_key:
                raise GeminiFailure('authentication')
            response = self.client.get(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.c['model']}",
                headers={'x-goog-api-key': self.api_key}, timeout=10)
            self.diagnostic['http_status'] = response.status_code
            if response.status_code >= 400:
                raise GeminiFailure({400:'invalid_request',401:'authentication',403:'permission',
                    404:'model_not_found',429:'quota'}.get(response.status_code,'server_error'))
            if 'generateContent' not in response.json().get('supportedGenerationMethods', []):
                raise GeminiFailure('generation_unsupported')
            if generate:
                self.diagnostic = {'phase': 'generation', 'http_status': None}
                self._gemini_once([{'role': 'user', 'content': 'Responda apenas: OK.'}], tools=None)
            self.connection_status = 'ok' if generate else 'available'
        except Exception as exc:
            self.connection_status = 'error'
            self.last_error = (exc.code if isinstance(exc, GeminiFailure) else
                               'timeout' if isinstance(exc, httpx.TimeoutException) else
                               'connection' if isinstance(exc, httpx.RequestError) else 'invalid_response')
        if generate and self.last_error == 'model_not_found':
            self.diagnostic['catalog'] = self.available_models()
            self.diagnostic['stable_probe'] = self.probe_stable_generation()
        BUS.emit('service', '', service='gemini', status=self.connection_status, error_code=self.last_error)
        return self.connection_status

    @staticmethod
    def safe_error(response):
        # Only fixed categories; never return raw messages, IDs or request content.
        result = {'http_status': response.status_code}
        try:
            error = response.json().get('error', {})
            status = error.get('status')
            if status in {'NOT_FOUND', 'INVALID_ARGUMENT', 'PERMISSION_DENIED',
                          'UNAUTHENTICATED', 'RESOURCE_EXHAUSTED', 'UNAVAILABLE', 'INTERNAL'}:
                result['api_status'] = status
            message = str(error.get('message', '')).casefold()
            if 'api version' in message:
                result['reason'] = 'model_or_api_version'
            elif 'not supported' in message:
                result['reason'] = 'unsupported_operation'
            elif 'not found' in message:
                result['reason'] = 'resource_not_found'
            elif 'no longer' in message or 'deprecated' in message or 'retired' in message:
                result['reason'] = 'model_retired'
            else:
                result['reason'] = 'unspecified'
        except Exception:
            result['reason'] = 'non_json_response'
        return result

    def probe_stable_generation(self):
        """Explicit diagnostic only: no history, tools, fallback or config changes."""
        try:
            response = self.client.post(
                f"https://generativelanguage.googleapis.com/v1/models/{self.c['model']}:generateContent",
                headers={'x-goog-api-key': self.api_key}, timeout=20,
                json={'contents': [{'role': 'user', 'parts': [{'text': 'Responda apenas: OK.'}]}]})
            if response.status_code >= 400:
                return self.safe_error(response)
            candidates = response.json().get('candidates', [])
            answered = any(p.get('text', '').strip() for c in candidates
                           for p in c.get('content', {}).get('parts', []) if not p.get('thought'))
            return {'http_status': response.status_code, 'answered': answered}
        except Exception:
            return {'reason': 'probe_unavailable'}

    def available_models(self):
        """Bounded catalog lookup; return public model IDs, never raw API errors."""
        names, token = [], None
        try:
            for _ in range(3):
                params = {'pageSize': 100}
                if token:
                    params['pageToken'] = token
                response = self.client.get('https://generativelanguage.googleapis.com/v1beta/models',
                    headers={'x-goog-api-key': self.api_key}, params=params, timeout=10)
                if response.status_code != 200:
                    return {'status': 'error', 'http_status': response.status_code, 'models': []}
                data = response.json()
                for item in data.get('models', []):
                    name = item.get('name', '')
                    if ('generateContent' in item.get('supportedGenerationMethods', [])
                            and re.fullmatch(r'models/gemini-[a-zA-Z0-9._-]+', name)):
                        names.append(name.removeprefix('models/'))
                token = data.get('nextPageToken')
                if not token:
                    break
            return {'status': 'ok', 'models': sorted(set(names)), 'complete': not bool(token),
                    'configured_model_listed': self.c['model'] in names}
        except Exception:
            return {'status': 'unavailable', 'models': []}


    def _ollama_stream(self, messages, tools=None):
        payload = {
            "model": self.c["model"], "messages": messages,
            "stream": True,
            "options": {
                "num_ctx": self.c.get("num_ctx", 4096),
                "num_gpu": self.c.get("num_gpu_layers", 999),
                "temperature": self.c.get("temperature", 0.4),
            },
        }
        if tools:
            payload["tools"] = tools
        with self.client.stream("POST", "/api/chat", json=payload) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                msg = data.get("message") or {}
                for call in msg.get("tool_calls") or []:
                    fn = call.get("function", {})
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        try: args = json.loads(args)
                        except json.JSONDecodeError: args = {}
                    yield ("tool", {"name": fn.get("name"), "args": args or {}})
                if msg.get("content"):
                    yield ("token", msg["content"])
                if data.get("done"):
                    break

    @staticmethod
    def _gemini_contents(messages):
        contents = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                continue
            if role == "user":
                contents.append({"role": "user", "parts": [{"text": str(m.get("content", ""))}]})
            elif role == "assistant":
                if m.get('gemini_content'):
                    contents.append(m['gemini_content'])
                    continue
                parts = []
                if m.get("content"):
                    parts.append({"text": m["content"]})
                for tc in m.get("tool_calls") or []:
                    fn = tc.get("function", {})
                    parts.append({"functionCall": {
                        "name": fn.get("name"),
                        "args": fn.get("arguments") or {},
                    }})
                if parts:
                    contents.append({"role": "model", "parts": parts})
            elif role == "tool":
                # Preserve signed model content and answer every requested call.
                # The orchestrator executes one call at a time with its safety gates.
                calls = []
                if contents and contents[-1]['role'] == 'model':
                    calls = [p['functionCall'] for p in contents[-1]['parts'] if 'functionCall' in p]
                responses = []
                selected = m.get('name') or (calls[0]['name'] if calls else 'unknown')
                used = False
                for call in calls or [{'name': selected}]:
                    executed = call['name'] == selected and not used
                    used = used or executed
                    response = {'name': call['name'], 'response': {'result':
                        str(m.get('content', ''))[:4000] if executed else
                        'Não executado nesta rodada. Solicite esta ferramenta separadamente.'}}
                    if call.get('id'):
                        response['id'] = call['id']
                    responses.append({'functionResponse': response})
                contents.append({'role': 'user', 'parts': responses})
        return contents

    def _generation_config(self):
        config = {'maxOutputTokens': self.c.get('max_output_tokens', 1024)}
        if self.c['model'] in ('gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'gemini-3.8-flash'):
            config['thinkingConfig'] = {'thinkingLevel': 'low'}
        # Gemini 3+ uses default sampling; 3.6+ ignores custom temperature.
        if not re.match(r'gemini-[3-9]', self.c['model']):
            config['temperature'] = self.c.get('temperature', 0.4)
        return config

    def _request_generation(self, body):
        """Retry only explicit transient HTTP failures, never a tool execution."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.c['model']}:generateContent"
        deadline = time.monotonic() + max(1, min(30, float(self.c.get('timeout_seconds', 30))))
        for attempt in range(3):
            remaining = max(.1, deadline - time.monotonic())
            self.diagnostic = {'phase': 'generation', 'http_status': None, 'attempts': attempt + 1}
            response = self.client.post(url, headers={
                'x-goog-api-key': self.api_key, 'Content-Type': 'application/json'},
                json=body, timeout=remaining)
            self.diagnostic = {'phase': 'generation', 'http_status': response.status_code,
                               'attempts': attempt + 1}
            delay = 2 ** attempt
            if (response.status_code not in (502, 503, 504) or attempt == 2
                    or time.monotonic() + delay >= deadline):
                return response
            BUS.emit('service', '', service='gemini', status='retrying',
                     model=self.c['model'], attempt=attempt + 2)
            time.sleep(delay)
        return response

    def _gemini_once(self, messages, tools=None):
        system = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
        body = {
            "systemInstruction": {"parts": [{"text": system}]} if system else None,
            "contents": self._gemini_contents(messages),
            "generationConfig": self._generation_config(),
        }
        if body["systemInstruction"] is None:
            del body["systemInstruction"]
        gt = _gemini_tools(tools)
        if gt:
            body["tools"] = gt
            body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}

        r = self._request_generation(body)
        if r.status_code >= 400:
            self.diagnostic.update(self.safe_error(r))
            raise GeminiFailure({400:"invalid_request",401:"authentication",403:"permission",404:"model_not_found",429:"quota"}.get(r.status_code,"server_error"))
        data = r.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise GeminiFailure("empty_response")
        if candidates[0].get('finishReason') == 'MALFORMED_FUNCTION_CALL':
            raise GeminiFailure('malformed_function_call')
        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            fc = part.get("functionCall")
            if fc:
                BUS.emit("tool", f"Gemini solicitou {fc.get('name')}")
                return ("tool", {"name": fc.get("name"), "args": fc.get("args") or {}, "gemini_content": candidates[0]["content"]})
        text = "".join(p.get("text", "") for p in parts if p.get("text"))
        if not text.strip():
            raise GeminiFailure('empty_response')
        return ("text", text.strip())

    def chat_stream(self, messages, tools=None):
        """Compatibility generator used by the existing orchestrator."""
        if self.backend == "ollama":
            yield from self._ollama_stream(messages, tools)
            return
        try:
            with measure('gemini_ms'):
                kind, payload = self._gemini_once(messages, tools)
            self.connection_status = 'ok'
        except Exception as exc:
            self.connection_status = 'error'
            self.last_error = (exc.code if isinstance(exc, GeminiFailure) else
                               'timeout' if isinstance(exc, httpx.TimeoutException) else 'connection')
            BUS.emit('service', '', service='gemini', status='error', error_code=self.last_error)
            raise GeminiFailure(self.last_error) from None
        self.last_error = None
        BUS.emit('service', '', service='gemini', status='ok')
        if kind == "tool":
            yield ("tool", payload)
        else:
            yield ("token", payload)


    def plan_search(self, question):
        """Text-only planning: never invokes tools or sends core/user memory."""
        prompt = ('Formule duas consultas de pesquisa para esta pergunta. Preserve todos os nomes próprios, '
                  'franquias, títulos e termos técnicos. Resolva o significado, não responda à pergunta. '
                  'Prefira inglês para ficção/tecnologia se ajudar. Não reduza a uma palavra genérica. '
                  'Retorne apenas JSON: {"queries":["consulta 1","consulta 2"]}.')
        with measure('gemini_ms'):
            kind,text = self._gemini_once([{'role':'system','content':prompt},
                                          {'role':'user','content':question}], tools=None)
        if kind != 'text':
            return []
        text=text.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()
        data=json.loads(text)
        return data.get('queries',[]) if isinstance(data,dict) else []

    def analyze_image(self, path: str, prompt: str) -> str:
        """Send one local image to Gemini for visual understanding. The image stays on disk locally;
        its bytes are included only in this Gemini request. This is intentionally separate from
        the normal text/tool loop so vision can be used as a local tool.
        """
        if self.backend != "gemini":
            return "vision requires the Gemini backend"
        from pathlib import Path
        import mimetypes, base64
        data = Path(path).read_bytes()
        mime = mimetypes.guess_type(path)[0] or "image/png"
        body = {
            "contents": [{"role": "user", "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode("ascii")}},
            ]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": min(2048, self.c.get("max_output_tokens", 1024) * 2),
            },
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.c['model']}:generateContent"
        r = self.client.post(url, headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"}, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"Gemini vision API {r.status_code}: {r.text[:1000]}")
        data = r.json()
        parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if p.get("text"))
        return text.strip() or "Gemini returned no visual description."

    def prefetch(self, partial: str):
        # Gemini calls are intentionally not made on every partial transcript:
        # doing so adds latency/cost and can race the final request.
        BUS.emit("llm", f'partial received → "{partial}"')
