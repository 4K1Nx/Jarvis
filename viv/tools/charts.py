"""Gráficos na HUD: números ficam melhores desenhados do que ditos.

Um gráfico é um dicionário simples que a tela anima (web/charts.js): medidores (anéis de 0 ao máximo), barras,
linhas ou pizza. Todo valor é validado aqui; a tela só recebe números e textos curtos.
"""
from viv.bus import BUS
from viv.tools.registry import tool

KINDS = ("medidores", "barras", "linhas", "pizza")


def chart(kind: str, items, unit: str = "") -> dict:
    """Monta um gráfico válido a partir de itens {label, value, max?, unit?, text?}."""
    kind = str(kind or "").casefold().strip()
    if kind not in KINDS:
        raise ValueError("tipo de gráfico: use medidores, barras, linhas ou pizza")
    clean = []
    for item in items or []:
        try:
            value = float(item["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if value != value or value in (float("inf"), float("-inf")):
            continue
        entry = {"label": str(item.get("label", ""))[:40], "value": round(value, 2)}
        if item.get("max") is not None:
            entry["max"] = max(float(item["max"]), 1e-9)
        for key in ("unit", "text"):
            if item.get(key):
                entry[key] = str(item[key])[:24]
        clean.append(entry)
    clean = clean[:6 if kind in ("medidores", "pizza") else 24 if kind == "linhas" else 12]
    if len(clean) < (2 if kind in ("linhas", "pizza") else 1):
        raise ValueError("o gráfico precisa de valores numéricos (pelo menos dois em linhas e pizza)")
    if kind == "pizza" and (min(i["value"] for i in clean) < 0 or sum(i["value"] for i in clean) <= 0):
        kind = "barras"
    return {"type": kind, "items": clean, "unit": str(unit or "")[:12]}


def show(title: str, data: dict, body: str = "", live: str = "") -> None:
    """Mostra o gráfico num painel. Com `live`, o painel já aberto com o mesmo nome é atualizado no lugar."""
    BUS.emit("card", title, kind="chart", chart=data, body=body, live=live, ok=True)


@tool("hud_grafico", "Mostrar números num gráfico animado na tela: use sempre que for falar de três ou mais números, de "
      "comparações, de evolução no tempo ou de partes de um todo, em vez de só ditá-los. medidores: percentuais ou "
      "valores contra um máximo; barras: comparar itens; linhas: evolução; pizza: partes de um todo.",
      {"titulo": {"type": "string"},
       "tipo": {"type": "string", "description": "medidores | barras | linhas | pizza"},
       "rotulos": {"type": "array", "items": {"type": "string"}, "description": "um nome curto por valor"},
       "valores": {"type": "array", "items": {"type": "number"}},
       "unidade": {"type": "string", "description": "ex.: %, GB, R$, ms", "required": False},
       "maximo": {"type": "number", "description": "só medidores: o valor que enche o anel (padrão 100)", "required": False}},
      card=False, title="Gráfico")
def hud_grafico(titulo, tipo, rotulos, valores, unidade="", maximo=None, ctx=None):
    labels, values = list(rotulos or []), list(valores or [])
    if len(labels) != len(values):
        raise ValueError("rotulos e valores precisam ter o mesmo tamanho")
    limit = float(maximo) if maximo else 100.0
    items = [{"label": label, "value": value, "max": limit if str(tipo).casefold().strip() == "medidores" else None}
             for label, value in zip(labels, values)]
    show(str(titulo)[:80], chart(tipo, items, unidade))
    return "gráfico exibido na tela; comente os números em uma ou duas frases, sem ler todos"
