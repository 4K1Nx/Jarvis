"""Modelos locais do Ollama: ver o que está instalado e baixar um novo, sempre com a permissão do usuário."""
import os
import re

from viv.tools import local
from viv.tools.registry import progress, tool

NAME = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,60}(:[a-z0-9._-]{1,40})?$")


def folder(ctx) -> str:
    """Onde o Ollama guarda os modelos nesta máquina."""
    return os.environ.get("OLLAMA_MODELS") or local.settings(ctx)["models_dir"]


def _user_folder() -> str:
    """A pasta configurada para o usuário no Windows (vale para o Ollama aberto pelo menu Iniciar)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return str(winreg.QueryValueEx(key, "OLLAMA_MODELS")[0])
    except Exception:
        return ""


@tool("modelos_locais", "Ver os modelos de IA locais (Ollama) instalados no computador, para que serve cada um, quais ainda "
      "faltam e em que modo você os usa. Use quando o usuário perguntar sobre os modelos locais ou quando precisar de um.",
      {}, title="Modelos locais")
def modelos_locais(ctx=None):
    conf, found = local.settings(ctx), local.installed(ctx)
    if not found:
        return ("o Ollama não respondeu ou não há modelos instalados. Peça ao usuário para abrir o Ollama; para baixar um "
                "modelo, pergunte se pode e use modelo_baixar")
    names = {m["nome"] for m in found}
    lines = [f"{m['nome']} ({m['gb']} GB)" for m in found]
    missing = [f"{conf[key]} — {use}" for key, use in local.USES.items() if conf[key] not in names and f"{conf[key]}:latest" not in names]
    return (f"modo de uso: {conf['mode']}. Pasta dos modelos: {_user_folder() or folder(ctx)}.\nInstalados: " + "; ".join(lines)
            + ("\nFaltam (pergunte ao usuário se pode baixar): " + "; ".join(missing) if missing else "\nTodos os modelos que você usa estão instalados."))


def _confirm(args: dict) -> str:
    name = str(args.get("nome", "")).strip().casefold()
    if not NAME.match(name):
        raise ValueError("nome de modelo inválido; use o nome do catálogo do Ollama, como qwen3:8b")
    return f"Baixar o modelo local {name} em {_user_folder() or local.DEFAULTS['models_dir']}? Pode ocupar vários GB e usar a internet por um bom tempo."


@tool("modelo_baixar", "Baixar um modelo de IA local pelo Ollama, para você usar sem gastar a cota do Gemini. Antes de chamar, "
      "diga ao usuário qual modelo, para que serve, o tamanho aproximado e a pasta onde vai ficar, e pergunte se pode; se "
      "ele quiser outra pasta, explique que a pasta dos modelos do Ollama é uma só e é trocada nas variáveis do Windows "
      "(OLLAMA_MODELS). Exige confirmação. O download segue em segundo plano e você avisa quando terminar.",
      {"nome": {"type": "string", "description": "nome no catálogo do Ollama, ex.: qwen3:8b, gemma3:4b, qwen2.5-coder:7b"}},
      dangerous=True, card=False, title="Baixando modelo local", confirm=_confirm)
def modelo_baixar(nome, ctx=None):
    name = str(nome).strip().casefold()
    if not NAME.match(name):
        raise ValueError("nome de modelo inválido; use o nome do catálogo do Ollama, como qwen3:8b")
    if local.has(ctx, name):
        return f"o modelo {name} já está instalado"
    progress(f"Baixando {name}")
    local.pull(ctx, name, progress)
    return f"modelo {name} baixado e pronto para uso"
