"""Busca na web e abertura de páginas no navegador padrão."""
import webbrowser

from viv.bus import BUS
from viv.tools.registry import tool


def search(query: str, max_results: int = 4) -> list[dict]:
    from ddgs import DDGS
    hits = DDGS(timeout=10).text(query, region="br-pt", max_results=max_results)
    return [{"title": h.get("title", ""), "url": h.get("href", ""), "body": h.get("body", "")} for h in hits]


@tool("web_search", "Pesquisar na web e devolver resultados curtos com as fontes. Use sempre que a resposta "
      "depender de informação atual.", {"query": {"type": "string"}}, card=False)
def web_search(query, ctx=None):
    hits = search(query)
    if not hits:
        BUS.emit("card", f"Pesquisa: {query}", kind="search", body="Nenhum resultado encontrado.", sources=[], ok=True)
        return "Nenhum resultado encontrado."
    BUS.emit("card", f"Pesquisa: {query}", kind="search", body=hits[0]["body"][:240],
             sources=[{"title": h["title"], "url": h["url"]} for h in hits], ok=True)
    return "\n".join(f"{h['title']}: {h['body'][:180]} ({h['url']})" for h in hits)


@tool("web_open", "Abrir um endereço no navegador padrão do usuário.", {"url": {"type": "string"}}, title="Abrindo site")
def web_open(url, ctx=None):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"{url} aberto"
