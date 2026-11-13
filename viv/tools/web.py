"""Busca na web e abertura de páginas no navegador padrão."""
import webbrowser

from viv.bus import BUS
from viv.tools.registry import tool


def search(query: str, max_results: int = 5) -> list[dict]:
    """Busca no DuckDuckGo. Tenta com e sem região; sem resultado devolve lista vazia em vez de erro."""
    from ddgs import DDGS
    last = None
    for options in ({"region": "br-pt"}, {}):
        try:
            hits = DDGS(timeout=10).text(query, max_results=max_results, **options)
            if hits:
                return [{"title": h.get("title", ""), "url": h.get("href", ""), "body": h.get("body", "")} for h in hits]
        except Exception as exc:
            last = exc
    if last is not None and "no results" not in str(last).lower():
        raise RuntimeError(f"a pesquisa falhou agora ({str(last)[:120]}); tente de novo em instantes")
    return []


@tool("web_search", "Pesquisar na web. Mostra na tela um painel com o resumo de cada fonte. Use sempre que a resposta "
      "depender de informação atual. Com abrir_guias, abre as melhores fontes em guias do navegador: use 2 ou 3 quando "
      "o usuário pedir para pesquisar, procurar ou mostrar algo; use 0 para uma consulta rápida.",
      {"query": {"type": "string"},
       "abrir_guias": {"type": "integer", "description": "quantas fontes abrir no navegador (0 a 3)", "required": False}},
      card=False, title="Pesquisa na web")
def web_search(query, abrir_guias=0, ctx=None):
    hits = search(query)
    if not hits:
        BUS.emit("card", f"Pesquisa: {query}", kind="search", body="Nenhum resultado encontrado.", results=[], ok=True)
        return "Nenhum resultado encontrado."
    results = [{"title": h["title"], "url": h["url"], "body": h["body"][:260]} for h in hits]
    BUS.emit("card", f"Pesquisa: {query}", kind="search", results=results, ok=True)
    opened = 0
    if getattr(ctx, "origin", ""):
        abrir_guias = 0                               # pedido pelo WhatsApp: abrir guias no PC do dono não ajuda ninguém
    for hit in hits[:max(0, min(3, int(abrir_guias or 0)))]:
        if hit["url"].startswith(("http://", "https://")):
            webbrowser.open(hit["url"])
            opened += 1
    text = "\n".join(f"{h['title']}: {h['body'][:220]} ({h['url']})" for h in hits)
    note = f"{opened} guia(s) aberta(s) no navegador; resultados também no painel da tela" if opened else \
        "resultados exibidos no painel da tela"
    return f"{text}\n[{note}]"


@tool("web_open", "Abrir um endereço no navegador padrão do usuário.", {"url": {"type": "string"}}, title="Abrindo site")
def web_open(url, ctx=None):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"{url} aberto"
