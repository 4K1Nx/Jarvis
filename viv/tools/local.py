"""Modelos locais do Ollama: a Viv os usa para poupar a cota do Gemini e para não parar quando ela acaba.

Só as tarefas de texto e de visão passam por aqui; a conversa por voz continua no Gemini Live. Modos
(ajuste "ia.local"): `reserva` usa o Ollama quando o Gemini falha por cota ou sobrecarga; `economia` usa o
Ollama primeiro e o Gemini quando o modelo local não dá conta; `desligado` nunca usa.
Baixar modelo é sempre com a permissão do usuário (ferramenta modelo_baixar, em viv/tools/modelos.py).
"""
import base64
import json
import os

HOST = "http://127.0.0.1:11434"
DEFAULTS = {"text_model": "qwen3:8b", "vision_model": "gemma3:4b", "code_model": "qwen2.5-coder:7b",
            "models_dir": r"E:\IA\Models", "mode": "reserva"}
USES = {"text_model": "texto: resumos, roteiros, documentos", "vision_model": "ver imagens e a tela",
        "code_model": "programar (agente de código local)"}
MODES = ("reserva", "economia", "desligado")
MAX_CHARS = 24000          # pedido maior que isso não cabe bem no contexto de um modelo local
CONTEXT = 8192
TIMEOUT = 300


class Missing(RuntimeError):
    """O modelo local necessário não está instalado (ou o Ollama não está rodando)."""


def settings(ctx) -> dict:
    cfg = getattr(ctx, "cfg", None) or {}
    data = {**DEFAULTS, **(cfg.get("tools", {}).get("local") or {})}
    chosen = getattr(ctx, "settings", None)
    if chosen is not None:
        try:
            data["mode"] = chosen.get("ia.local") or data["mode"]
        except Exception:
            pass
    data["mode"] = str(data["mode"]).casefold().strip()
    if data["mode"] not in MODES:
        data["mode"] = "reserva"
    data["host"] = str(data.get("host") or os.environ.get("OLLAMA_HOST") or HOST).rstrip("/")
    if not data["host"].startswith("http"):
        data["host"] = "http://" + data["host"]
    return data


def _http(method: str, url: str, payload: dict | None = None, timeout: float = TIMEOUT) -> dict:
    import httpx
    reply = httpx.request(method, url, json=payload, timeout=timeout)
    if reply.status_code >= 400:
        raise RuntimeError(f"Ollama respondeu {reply.status_code}: {reply.text[:200]}")
    return reply.json()


def installed(ctx, http=None) -> list[dict]:
    """Os modelos instalados: nome e tamanho em GB. Ollama parado devolve lista vazia."""
    try:
        data = (http or _http)("GET", settings(ctx)["host"] + "/api/tags", None, 5)
    except Exception:
        return []
    return [{"nome": m.get("name", ""), "gb": round(m.get("size", 0) / 1e9, 1)} for m in data.get("models", [])]


def has(ctx, model: str, http=None) -> bool:
    names = {m["nome"] for m in installed(ctx, http)}
    return model in names or f"{model}:latest" in names


def generate(ctx, prompt: str, as_json: bool = False, image: bytes | None = None, http=None) -> str:
    """Resposta de um modelo local. Levanta Missing se o modelo não estiver instalado."""
    conf = settings(ctx)
    model = conf["vision_model" if image is not None else "text_model"]
    if not has(ctx, model, http):
        raise Missing(f"o modelo local {model} não está instalado ou o Ollama não está aberto. Pergunte ao usuário se "
                      f"pode baixar ({conf['models_dir']}) e, com o sim dele, use modelo_baixar")
    payload = {"model": model, "prompt": prompt, "stream": False, "think": False, "options": {"num_ctx": CONTEXT}}
    if as_json:
        payload["format"] = "json"
    if image is not None:
        payload["images"] = [base64.b64encode(image).decode("ascii")]
    call = http or _http
    try:
        data = call("POST", conf["host"] + "/api/generate", payload, TIMEOUT)
    except RuntimeError as exc:
        if "think" not in str(exc).casefold():
            raise
        payload.pop("think")                   # modelo que não tem modo de raciocínio recusa o parâmetro
        data = call("POST", conf["host"] + "/api/generate", payload, TIMEOUT)
    text = str(data.get("response") or "").strip()
    if not text:
        raise RuntimeError(f"o modelo local {model} não devolveu resposta")
    return text


def pull(ctx, model: str, progress=None, stream=None) -> None:
    """Baixa um modelo pelo Ollama, relatando o andamento. `stream` devolve as linhas JSON do servidor."""
    def lines():
        import httpx
        with httpx.stream("POST", settings(ctx)["host"] + "/api/pull", json={"model": model}, timeout=None) as reply:
            reply.raise_for_status()
            yield from reply.iter_lines()
    for line in (stream or lines)():
        if not line:
            continue
        event = json.loads(line)
        if event.get("error"):
            raise RuntimeError(f"o download de {model} falhou: {event['error']}")
        total, done = event.get("total") or 0, event.get("completed") or 0
        if progress is not None:
            progress(f"Baixando {model}: {event.get('status', '')}"[:110], done / total if total else None)


# ---- chat: conversar por texto direto com um modelo instalado -----------------------------------------
CHAT_SYSTEM = "Responda em português do Brasil, a menos que o usuário escreva ou peça outro idioma."
CHAT_TURNS = 40            # mensagens da conversa que o modelo relê a cada resposta


def chat_models(ctx, http=None) -> list[dict]:
    """Modelos com que dá para conversar (os de embeddings ficam de fora)."""
    return [m for m in installed(ctx, http) if m["nome"] and "embed" not in m["nome"].casefold()]


def chat(ctx, model: str, messages: list[dict], on_text=None, stream=None) -> str:
    """Resposta de `model` à conversa `messages` ({"role", "content"}). `on_text(texto até aqui)` é chamado
    conforme a resposta chega. `stream(payload)` devolve as linhas JSON do servidor."""
    conf = settings(ctx)
    payload = {"model": model, "stream": True, "think": False, "options": {"num_ctx": CONTEXT},
               "messages": [{"role": "system", "content": CHAT_SYSTEM}] + messages[-CHAT_TURNS:]}

    def lines(body):
        import httpx
        with httpx.stream("POST", conf["host"] + "/api/chat", json=body, timeout=TIMEOUT) as reply:
            if reply.status_code >= 400:
                raise RuntimeError(f"Ollama respondeu {reply.status_code}: {reply.read().decode('utf-8', 'replace')[:200]}")
            yield from reply.iter_lines()

    def run(body):
        text = ""
        for line in (stream or lines)(body):
            if not line:
                continue
            event = json.loads(line)
            if event.get("error"):
                raise RuntimeError(str(event["error"]))
            piece = (event.get("message") or {}).get("content") or ""
            if piece:
                text += piece
                if on_text is not None:
                    on_text(text)
        return text.strip()
    try:
        text = run(payload)
    except RuntimeError as exc:
        if "think" not in str(exc).casefold():
            raise
        payload.pop("think")                   # modelo sem modo de raciocínio recusa o parâmetro
        text = run(payload)
    if not text:
        raise RuntimeError(f"o modelo {model} não devolveu resposta")
    return text
