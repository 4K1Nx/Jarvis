"""Captura da tela e análise visual pelo Gemini."""
from pathlib import Path

from viv.bus import BUS
from viv.tools.registry import tool

DEFAULT_QUESTION = "Descreva o que está na tela: janelas, textos importantes, erros visíveis e elementos clicáveis."


def capture(path: str) -> str:
    from PIL import ImageGrab
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab().save(path)
    return path


@tool("vision_analyze_screen", "Capturar a tela e analisar o que está visível. Use quando a resposta depender "
      "do que aparece na tela do usuário.", {"question": {"type": "string", "required": False}}, card=False)
def analyze_screen(question=DEFAULT_QUESTION, ctx=None):
    cfg = ctx.cfg.get("tools", {}).get("vision", {})
    path = capture(cfg.get("screenshot_path", "data/screen.png"))
    if ctx.client is None:
        raise RuntimeError("análise visual indisponível: sem conexão com o Gemini")
    from google.genai import types
    image = types.Part.from_bytes(data=Path(path).read_bytes(), mime_type="image/png")
    response = ctx.client.models.generate_content(
        model=cfg.get("model", "gemini-3.8-flash"),
        contents=[image, question + " Responda em português, de forma objetiva."])
    result = (response.text or "").strip() or "não consegui interpretar a tela"
    BUS.emit("card", "Tela analisada", kind="vision", body=result[:300], image="/api/screen", ok=True)
    return result[:8000]
