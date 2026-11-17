"""Captura da tela, análise visual pelo Gemini e vigia da tela."""
import time
from pathlib import Path

from viv.bus import BUS
from viv.tools import _llm
from viv.tools.registry import tool

DEFAULT_QUESTION = "Descreva o que está na tela: janelas, textos importantes, erros visíveis e elementos clicáveis."


def capture(path: str) -> str:
    from PIL import ImageGrab
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab().save(path)
    return path


def generate(client, model: str, contents: list, sleep=time.sleep) -> str:
    """Pergunta ao modelo de visão, com novas tentativas e modelos reserva em falha passageira."""
    return _llm.generate(client, model, contents, sleep=sleep, label="de visão")


def look(ctx, question: str) -> str:
    cfg = ctx.cfg.get("tools", {}).get("vision", {})
    path = capture(cfg.get("screenshot_path", "data/screen.png"))
    data, ask = Path(path).read_bytes(), question + " Responda em português, de forma objetiva."
    try:
        if ctx.client is None:
            raise RuntimeError("análise visual indisponível: sem conexão com o Gemini")
        from google.genai import types
        image = types.Part.from_bytes(data=data, mime_type="image/png")
        return generate(ctx.client, cfg.get("model", "gemini-3.8-flash"), [image, ask])
    except Exception as failure:
        # o Gemini falhou (cota, sobrecarga, prazo): um modelo local de visão olha a tela no lugar dele
        from viv.tools import local
        if local.settings(ctx)["mode"] == "desligado":
            raise
        try:
            return local.generate(ctx, ask, image=data)
        except local.Missing as missing:
            raise RuntimeError(f"{failure}. Um modelo local poderia assumir: {missing}") from None
        except Exception:
            raise failure from None


@tool("vision_analyze_screen", "Capturar a tela e analisar o que está visível. Use quando a resposta depender "
      "do que aparece na tela do usuário (um download, um erro, um progresso). Para clicar em algo, não analise antes: "
      "chame tela_clicar direto, que já olha a tela e acha o lugar.",
      {"question": {"type": "string", "required": False}}, card=False)
def analyze_screen(question=DEFAULT_QUESTION, ctx=None):
    result = look(ctx, question) or "não consegui interpretar a tela"
    BUS.emit("card", "Tela analisada", kind="vision", body=result[:600], image="/api/screen", ok=True)
    return result[:8000]


@tool("tela_vigiar", "Vigiar a tela em segundo plano e avisar o usuário em voz alta quando algo acontecer: um download "
      "ou instalação terminar, um erro aparecer, um progresso chegar ao fim. Continua vigiando mesmo com a Viv dormindo.",
      {"condicao": {"type": "string", "description": "o que observar, ex.: o download do Steam terminar"},
       "intervalo_segundos": {"type": "integer", "description": "de quanto em quanto tempo olhar (mínimo 20, padrão 60)", "required": False},
       "limite_minutos": {"type": "integer", "description": "por quanto tempo vigiar no máximo (padrão 180)", "required": False}},
      title="Vigiando a tela")
def tela_vigiar(condicao, intervalo_segundos=60, limite_minutos=180, ctx=None):
    return ctx.watch.start(condicao, intervalo_segundos, limite_minutos)


@tool("tela_parar_vigia", "Parar de vigiar a tela.", {}, title="Vigia da tela")
def tela_parar_vigia(ctx=None):
    return ctx.watch.stop()


@tool("tela_vigia_status", "Dizer o que a vigia da tela está observando e o último estado visto.", {}, title="Vigia da tela")
def tela_vigia_status(ctx=None):
    return ctx.watch.status()
