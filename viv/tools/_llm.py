"""Chamadas ao modelo de texto do Gemini usadas pelas ferramentas (visão, código, documentos, pesquisa)."""
import json
import re
import time

# Reservas para quando o modelo principal está sobrecarregado. O gemini-2.5-flash saiu da lista: foi
# desligado para contas novas e, sendo o último reserva, o erro dele (404) escondia a sobrecarga real.
FALLBACK_MODELS = ("gemini-3.7-flash", "gemini-3-flash-preview")
TIMEOUT_MS = 90_000        # prazo de cada chamada; vencido, conta como falha passageira e tenta o modelo reserva
GONE = ("404", "not_found", "not found", "no longer available", "is not supported")
TRANSIENT = ("503", "unavailable", "429", "resource_exhausted", "overloaded", "high demand", "deadline", "timeout", "timed out", "500")


def generate(client, model: str, contents, sleep=time.sleep, label: str = "de texto", config: dict | None = None,
             raw: bool = False):
    """Pergunta ao modelo. Em falha passageira (503, cota), tenta de novo e cai para modelos reserva.
    Devolve o texto, ou a resposta inteira com `raw` (para ler chamadas de ferramenta)."""
    first, busy = None, False
    # sem prazo, uma chamada presa segurava a tarefa indefinidamente (uma análise de tela já levou 20 minutos)
    extra = {"config": {"http_options": {"timeout": TIMEOUT_MS}, **(config or {})}}
    for name in dict.fromkeys((model,) + FALLBACK_MODELS):
        for attempt in range(2):
            try:
                response = client.models.generate_content(model=name, contents=contents, **extra)
                return response if raw else (response.text or "").strip()
            except Exception as exc:
                text = str(exc).lower()
                if any(marker in text for marker in GONE):
                    first = first or exc
                    break                             # esse modelo não existe para esta chave: tenta o próximo
                if not any(marker in text for marker in TRANSIENT):
                    raise
                first, busy = first or exc, True
                if attempt == 0:
                    sleep(1.5)
    if busy:
        raise RuntimeError(f"o serviço {label} está sobrecarregado agora; tente de novo em instantes ({str(first)[:80]})")
    raise RuntimeError(f"nenhum modelo {label} disponível para esta chave ({model} e reservas); ajuste tools.text.model "
                       f"no config.yaml ({str(first)[:80]})")


def parse_json(text: str):
    """JSON devolvido pelo modelo, com ou sem cerca de código em volta."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except ValueError:
        raise RuntimeError("o modelo devolveu uma resposta que não consegui ler; tente de novo") from None


def _local(ctx, prompt: str, as_json: bool):
    from viv.bus import BUS
    from viv.tools import local
    text = local.generate(ctx, prompt, as_json)
    BUS.emit("card", "Modelo local", kind="data", ok=True, body="Esta etapa rodou no seu computador, sem gastar a cota do Gemini.")
    return parse_json(text) if as_json else text


def ask(ctx, prompt: str, as_json: bool = False):
    """Resposta a `prompt`: texto, ou objeto quando `as_json`. Conforme o ajuste "ia.local", um modelo local do
    Ollama responde primeiro (economia) ou entra quando o Gemini falha (reserva); ver viv/tools/local.py."""
    from viv.tools import local
    mode = local.settings(ctx)["mode"]
    fits = mode != "desligado" and len(prompt) <= local.MAX_CHARS
    if fits and mode == "economia":
        try:
            return _local(ctx, prompt, as_json)
        except Exception:
            fits = False                       # o modelo local não deu conta: segue para o Gemini
    try:
        return _gemini(ctx, prompt, as_json)
    except Exception as failure:
        if not fits:
            raise
        try:
            return _local(ctx, prompt, as_json)
        except local.Missing as missing:
            raise RuntimeError(f"{failure}. Um modelo local poderia assumir: {missing}") from None
        except Exception:
            raise failure from None


def _gemini(ctx, prompt: str, as_json: bool = False):
    if ctx is None or ctx.client is None:
        raise RuntimeError("indisponível agora: sem conexão com o Gemini")
    tools = ctx.cfg.get("tools", {})
    model = tools.get("text", {}).get("model") or tools.get("vision", {}).get("model") or "gemini-3.8-flash"
    config = {"response_mime_type": "application/json", "max_output_tokens": 32768} if as_json else None
    text = generate(ctx.client, model, prompt, config=config)
    return parse_json(text) if as_json else text
