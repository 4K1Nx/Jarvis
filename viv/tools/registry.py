"""Registro das ferramentas locais expostas ao Gemini como declarações de função."""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from viv.bus import BUS
from viv.errors import ERRORS

_REG: dict[str, dict] = {}
_MODULES = ("desktop", "apps", "system", "optimize", "uninstall", "files", "browser", "web", "weather", "vision", "mail",
            "hud", "assistant", "settings_tools")


@dataclass
class Context:
    cfg: dict
    memory: Any = None
    reminders: Any = None
    client: Any = None
    settings: Any = None
    watch: Any = None
    mail_cache: Any = None


def tool(name: str, description: str, params: dict, dangerous: bool = False,
         title: str | None = None, card: bool = True, confirm=None):
    """Registra uma ferramenta. `title` é o rótulo do cartão na HUD; `card=False`
    quando a própria ferramenta emite um cartão específico. `confirm(args)` devolve o texto do
    cartão de confirmação de uma ação perigosa e pode levantar erro se o pedido for inválido."""
    def deco(fn):
        props = {k: {a: b for a, b in v.items() if a != "required"} for k, v in params.items()}
        _REG[name] = {
            "fn": fn, "dangerous": dangerous, "title": title or name, "card": card, "confirm": confirm,
            "declaration": {"name": name, "description": description, "parameters": {
                "type": "object", "properties": props,
                "required": [k for k, v in params.items() if v.get("required", True)]}},
        }
        return fn
    return deco


def declarations() -> list[dict]:
    return [t["declaration"] for t in _REG.values()]


def is_dangerous(name: str, cfg: dict) -> bool:
    return name in cfg.get("safety", {}).get("dangerous", []) or _REG.get(name, {}).get("dangerous", False)


def describe(name: str, args: dict | None) -> str:
    """Texto curto para cartões e confirmações: rótulo + argumentos."""
    title = _REG.get(name, {}).get("title", name)
    detail = ", ".join(str(v)[:60] for v in (args or {}).values())
    return f"{title}: {detail}" if detail else title


def confirm_text(name: str, args: dict | None) -> str:
    """Texto do cartão de confirmação. Levanta erro se a ferramenta rejeitar o pedido."""
    custom = _REG.get(name, {}).get("confirm")
    return custom(args or {}) if custom else describe(name, args)


def call(name: str, args: dict | None, ctx: Context) -> str:
    entry = _REG.get(name)
    if entry is None:
        return f"erro: ferramenta desconhecida ({name})"
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return "erro: argumentos inválidos"
    try:
        result = str(entry["fn"](ctx=ctx, **args))
    except Exception as exc:  # o modelo recebe o erro como texto e explica ao usuário
        BUS.emit("card", entry["title"], kind="action", body=str(exc)[:300], ok=False)
        ERRORS.record(name, f"{type(exc).__name__}: {exc}")
        return f"erro: {exc}"
    if entry["card"]:
        BUS.emit("card", describe(name, args), kind="action", body=result[:300], ok=True)
    return result


def load_all() -> None:
    for module in _MODULES:
        try:
            importlib.import_module(f"viv.tools.{module}")
        except ModuleNotFoundError as exc:
            if exc.name != f"viv.tools.{module}":
                raise
