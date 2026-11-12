"""Aplicativos instalados: lista do Menu Iniciar do Windows e abertura por nome aproximado."""
import difflib
import json
import os
import re
import shutil
import subprocess
import time
import unicodedata

from viv.bus import BUS
from viv.tools.registry import tool

_CACHE = {"at": 0.0, "apps": []}
_FILLER = {"o", "a", "os", "as", "do", "da", "de", "app", "aplicativo", "programa", "exe"}


def installed_apps() -> list[dict]:
    """[{Name, AppID}] do Menu Iniciar (inclui apps da Store). Cache de 5 minutos."""
    if _CACHE["apps"] and time.time() - _CACHE["at"] < 300:
        return _CACHE["apps"]
    command = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"
    out = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, timeout=20,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    data = json.loads(out.stdout.decode("utf-8", errors="replace") or "[]")
    apps = [a for a in (data if isinstance(data, list) else [data]) if a.get("Name") and a.get("AppID")]
    _CACHE.update(at=time.time(), apps=apps)
    return apps


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


def _key(text: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", _fold(text)) if w not in _FILLER]
    return "".join(words)


def find_app(query: str, apps: list[dict]) -> tuple[dict | None, list[str]]:
    """Melhor aplicativo para o nome falado e, sem casamento, sugestões parecidas."""
    wanted = _key(query)
    if not wanted:
        return None, []
    keyed = sorted(((_key(a["Name"]), a) for a in apps), key=lambda pair: len(pair[0]))
    initials = {"".join(w[0] for w in re.findall(r"[a-z0-9]+", _fold(a["Name"]))): a for _, a in keyed}
    for rule in (lambda k: k == wanted, lambda k: k.startswith(wanted), lambda k: wanted in k):
        for key, app in keyed:
            if key and rule(key):
                return app, []
    if wanted in initials:                       # "vscode" -> Visual Studio Code não casa; "vsc" casa
        return initials[wanted], []
    words = [w for w in re.findall(r"[a-z0-9]+", _fold(query)) if w not in _FILLER]
    for key, app in keyed:                       # "vs code": todas as palavras como prefixo de palavras do nome
        name_words = re.findall(r"[a-z0-9]+", _fold(app["Name"]))
        if words and _subsequence(words, name_words):
            return app, []
    close = difflib.get_close_matches(wanted, [k for k, _ in keyed], n=3, cutoff=0.72)
    if close:
        return next(a for k, a in keyed if k == close[0]), []
    loose = difflib.get_close_matches(wanted, [k for k, _ in keyed], n=4, cutoff=0.45)
    return None, [a["Name"] for k, a in keyed if k in loose]


def _subsequence(words: list[str], name_words: list[str]) -> bool:
    """O que foi dito se decompõe, em ordem, em inícios de palavras do nome?
    "vs code" e "vscode" casam com Visual Studio Code (v | s | code)."""
    text = "".join(words)

    def match(rest: str, start: int) -> bool:
        if not rest:
            return True
        for index in range(start, len(name_words)):
            for size in range(len(rest), 0, -1):
                if name_words[index].startswith(rest[:size]) and match(rest[size:], index + 1):
                    return True
        return False
    return len(text) >= 2 and match(text, 0)


@tool("desktop_launch_app", "Abrir um aplicativo instalado pelo nome (ex.: WhatsApp, Steam, Chrome, Spotify, bloco de notas). "
      "Aceita nome aproximado. Se não achar, devolve erro com nomes parecidos.",
      {"app": {"type": "string", "description": "nome do aplicativo como o usuário falou"}}, title="Abrindo aplicativo")
def launch_app(app, ctx=None):
    match, suggestions = find_app(app, installed_apps())
    if match is not None:
        subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + match["AppID"]])
        return f"{match['Name']} aberto"
    target = shutil.which(app) or (app if os.path.exists(os.path.expanduser(app)) else None)
    if target:
        os.startfile(os.path.expanduser(target))
        return f"{app} aberto"
    hint = f" Parecidos: {', '.join(suggestions)}." if suggestions else " Use desktop_list_apps para ver os instalados."
    raise LookupError(f"aplicativo '{app}' não encontrado.{hint}")


@tool("desktop_list_apps", "Listar os aplicativos instalados no computador, opcionalmente filtrando por um trecho do nome. "
      "Mostra a lista na tela.", {"filtro": {"type": "string", "required": False}}, card=False)
def list_apps(filtro=None, ctx=None):
    names = sorted({a["Name"] for a in installed_apps()}, key=_fold)
    if filtro:
        names = [n for n in names if _key(filtro) in _key(n)]
    title = f"Aplicativos com “{filtro}”" if filtro else f"Aplicativos instalados ({len(names)})"
    BUS.emit("card", title, kind="content", format="lista", body="\n".join(names) or "Nenhum aplicativo encontrado.", ok=True)
    if len(names) > 60:
        return f"{len(names)} aplicativos, lista completa exibida na tela. Alguns: {', '.join(names[:40])}"
    return ", ".join(names) or "nenhum aplicativo encontrado"
