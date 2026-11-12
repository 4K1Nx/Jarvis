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


@tool("desktop_hotkey", "Pressionar uma combinação de teclas, ex.: ctrl+s, alt+tab, win+d.",
      {"keys": {"type": "string", "description": "teclas separadas por +"}}, title="Atalho")
def hotkey(keys, ctx=None):
    _gui().hotkey(*[k.strip() for k in keys.split("+")])
    return f"pressionado {keys}"


@tool("desktop_click", "Mover o mouse e clicar em coordenadas absolutas da tela.",
      {"x": {"type": "integer"}, "y": {"type": "integer"}}, title="Clique")
def click(x, y, ctx=None):
    g = _gui()
    g.moveTo(int(x), int(y), duration=0.15)
    g.click()
    return f"clique em {x},{y}"


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
