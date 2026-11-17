"""Automação do desktop: aplicativos, teclado, mouse e shell."""
import os
import subprocess

from viv.tools.registry import tool


def _gui():
    import pyautogui
    pyautogui.FAILSAFE = True
    return pyautogui


@tool("desktop_type_text", "Digitar um texto na janela em foco.", {"text": {"type": "string"}}, title="Digitando")
def type_text(text, ctx=None):
    import keyboard
    keyboard.write(text, delay=0.01)  # suporta acentos, ao contrário do pyautogui
    return "texto digitado"


@tool("desktop_hotkey", "Apertar uma tecla ou uma combinação de teclas na janela em foco: enter, tab, esc, space, "
      "delete, up, down, left, right, pagedown, f5, ou combinações como ctrl+s, alt+tab, win+d. `vezes` repete.",
      {"keys": {"type": "string", "description": "uma tecla, ou várias separadas por +"},
       "vezes": {"type": "integer", "description": "quantas vezes apertar (padrão 1)", "required": False}}, title="Tecla")
def hotkey(keys, vezes=1, ctx=None):
    times = max(1, min(int(vezes or 1), 50))
    parts = [k.strip().lower() for k in str(keys).split("+") if k.strip()]
    if not parts:
        raise ValueError("informe a tecla")
    for _ in range(times):
        _gui().hotkey(*parts)
    return f"pressionado {keys}" + (f" {times} vezes" if times > 1 else "")


BUTTONS = {"esquerdo": "left", "direito": "right", "meio": "middle", "left": "left", "right": "right", "middle": "middle"}


def _click(x: int, y: int, botao="esquerdo", duplo=False) -> None:
    g = _gui()
    button = BUTTONS.get(str(botao or "esquerdo").casefold().strip())
    if button is None:
        raise ValueError("botão do mouse: esquerdo, direito ou meio")
    g.moveTo(int(x), int(y), duration=0.2)
    g.click(button=button, clicks=2 if duplo else 1, interval=0.08)


@tool("desktop_click", "Clicar em coordenadas exatas da tela, só quando o usuário ditar os números. Nunca estime "
      "coordenadas a partir de uma descrição da tela: para clicar num botão, link ou ícone, use tela_clicar.",
      {"x": {"type": "integer"}, "y": {"type": "integer"},
       "botao": {"type": "string", "description": "esquerdo (padrão), direito ou meio", "required": False},
       "duplo": {"type": "boolean", "description": "clique duplo", "required": False}}, title="Clique")
def click(x, y, botao="esquerdo", duplo=False, ctx=None):
    _click(x, y, botao, duplo)
    return f"clique em {x},{y}"


LOCATE = ("Nesta captura de tela, localize o elemento de interface descrito a seguir e devolva só um JSON "
          '{"box_2d": [ymin, xmin, ymax, xmax], "nome": "texto visível do elemento"}, com as coordenadas normalizadas de 0 a '
          '1000. Se houver mais de um, escolha o que melhor corresponde. Se não estiver visível, devolva {"box_2d": null}. '
          "Elemento: ")


def locate(ctx, target: str, ask=None, grab=None) -> tuple[int, int, str]:
    """Centro, em pixels da captura, do elemento descrito em `target`, e o nome que o modelo leu nele."""
    import io
    from viv.tools import _llm
    if grab is None:
        from PIL import ImageGrab
        grab = ImageGrab.grab
    image = grab()
    if ask is None:
        if ctx is None or ctx.client is None:
            raise RuntimeError("achar coisas na tela precisa da conexão com o Gemini")
        from google.genai import types
        raw = io.BytesIO()
        image.save(raw, "PNG")
        model = ctx.cfg.get("tools", {}).get("vision", {}).get("model", "gemini-3.8-flash")

        def ask(prompt):
            return _llm.generate(ctx.client, model, [types.Part.from_bytes(data=raw.getvalue(), mime_type="image/png"), prompt],
                                 label="de visão", config={"response_mime_type": "application/json"})
    data = _llm.parse_json(ask(LOCATE + target))
    if isinstance(data, list):
        data = data[0] if data else {}
    box = data.get("box_2d") if isinstance(data, dict) else None
    if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)):
        raise RuntimeError(f"não achei “{target}” na tela; descreva de outro jeito ou confira com vision_analyze_screen")
    ymin, xmin, ymax, xmax = (max(0.0, min(1000.0, float(v))) for v in box)
    width, height = image.size
    return round((xmin + xmax) / 2000 * width), round((ymin + ymax) / 2000 * height), str(data.get("nome") or target)[:80]


@tool("tela_clicar", "Clicar em algo que está visível na tela, descrito em palavras: um botão, um link, um ícone, um campo, "
      "uma aba, um item de menu (ex.: “botão Salvar”, “campo de busca do YouTube”, “ícone do Chrome na barra de "
      "tarefas”). É o jeito certo de clicar: a ferramenta olha a tela, acha o lugar e clica, tudo de uma vez. Para preencher um campo, clique nele e depois use "
      "desktop_type_text. Depois de clicar, se o resultado importar, confira com vision_analyze_screen.",
      {"alvo": {"type": "string", "description": "o que clicar, com o texto visível e onde fica, se ajudar"},
       "botao": {"type": "string", "description": "esquerdo (padrão), direito ou meio", "required": False},
       "duplo": {"type": "boolean", "description": "clique duplo (abrir arquivo ou ícone)", "required": False}},
      title="Clicando na tela")
def tela_clicar(alvo, botao="esquerdo", duplo=False, ctx=None):
    from viv.tools.registry import progress
    progress("Procurando na tela", 0.3)
    x, y, name = locate(ctx, str(alvo))
    g = _gui()
    from PIL import ImageGrab
    shot, screen = ImageGrab.grab().size, g.size()         # a captura pode ter mais pixels que as coordenadas do mouse
    x, y = round(x * screen[0] / shot[0]), round(y * screen[1] / shot[1])
    progress("Clicando", 0.8)
    _click(x, y, botao, duplo)
    return f"cliquei em “{name}” ({x},{y})"


@tool("desktop_scroll", "Rolar a página ou a lista sob o mouse, para baixo ou para cima.",
      {"direcao": {"type": "string", "description": "baixo ou cima"},
       "quantidade": {"type": "integer", "description": "quanto rolar, de 1 (pouco) a 20 (padrão 5)", "required": False}},
      title="Rolando")
def scroll(direcao, quantidade=5, ctx=None):
    amount = max(1, min(int(quantidade or 5), 20)) * 120
    up = str(direcao).casefold().strip() in ("cima", "up", "acima")
    _gui().scroll(amount if up else -amount)
    return f"rolei para {'cima' if up else 'baixo'}"


@tool("desktop_screenshot", "Salvar uma captura da tela em PNG.",
      {"path": {"type": "string", "required": False}}, title="Captura de tela")
def screenshot(path="data/screen.png", ctx=None):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    _gui().screenshot(path)
    return path


@tool("desktop_run_command", "Executar um comando no shell do Windows. Irreversível; exige confirmação.",
      {"command": {"type": "string"}}, dangerous=True, title="Comando no shell")
def run_command(command, ctx=None):
    out = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
    return (out.stdout or out.stderr or "comando concluído sem saída")[:2000]
