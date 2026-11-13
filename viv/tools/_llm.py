"""Chamadas ao modelo de texto do Gemini usadas pelas ferramentas (visão, código, documentos, pesquisa)."""
import json
import re
import time

FALLBACK_MODELS = ("gemini-3.7-flash", "gemini-2.5-flash")
TRANSIENT = ("503", "unavailable", "429", "resource_exhausted", "overloaded", "high demand", "deadline", "timeout", "500")


def generate(client, model: str, contents, sleep=time.sleep, label: str = "de texto", config: dict | None = None) -> str:
    """Pergunta ao modelo. Em falha passageira (503, cota), tenta de novo e cai para modelos reserva."""
    last = None
    extra = {"config": config} if config else {}
    for name in dict.fromkeys((model,) + FALLBACK_MODELS):
        for attempt in range(2):
            try:
                response = client.models.generate_content(model=name, contents=contents, **extra)
                return (response.text or "").strip()
            except Exception as exc:
                last = exc
                if not any(marker in str(exc).lower() for marker in TRANSIENT):
                    raise
                if attempt == 0:
                    sleep(1.5)
    raise RuntimeError(f"o serviço {label} está sobrecarregado agora; tente de novo em instantes ({str(last)[:80]})")


def parse_json(text: str):
    """JSON devolvido pelo modelo, com ou sem cerca de código em volta."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except ValueError:
        raise RuntimeError("o modelo devolveu uma resposta que não consegui ler; tente de novo") from None


def ask(ctx, prompt: str, as_json: bool = False):
    """Resposta do modelo de texto a `prompt`: texto, ou objeto quando `as_json`."""
    if ctx is None or ctx.client is None:
        raise RuntimeError("indisponível agora: sem conexão com o Gemini")
    tools = ctx.cfg.get("tools", {})
    model = tools.get("text", {}).get("model") or tools.get("vision", {}).get("model") or "gemini-3.8-flash"
    config = {"response_mime_type": "application/json", "max_output_tokens": 32768} if as_json else None
    text = generate(ctx.client, model, prompt, config=config)
    return parse_json(text) if as_json else text
