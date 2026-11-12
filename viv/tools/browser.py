"""Navegador visível controlado por Playwright, com perfil persistente.

O Playwright síncrono só pode ser usado pela thread que o iniciou, então todas as
chamadas passam por um executor de uma única thread.
"""
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote_plus

from viv.tools.registry import tool

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="viv-browser")
_STATE = {"pw": None, "context": None, "page": None}


def _page(ctx):
    page = _STATE["page"]
    if page is not None and not page.is_closed():
        return page
    cfg = ctx.cfg.get("tools", {}).get("browser", {})
    if _STATE["context"] is None:
        from playwright.sync_api import sync_playwright
        profile = Path("data") / "browser-profile"
        profile.mkdir(parents=True, exist_ok=True)
        _STATE["pw"] = sync_playwright().start()
        _STATE["context"] = _STATE["pw"].chromium.launch_persistent_context(
            str(profile), headless=bool(cfg.get("headless", False)))
        _STATE["context"].set_default_timeout(cfg.get("timeout_ms", 15000))
    context = _STATE["context"]
    _STATE["page"] = context.pages[0] if context.pages else context.new_page()
    return _STATE["page"]


def _on_browser_thread(fn):
    def wrapper(*args, ctx=None, **kwargs):
        return _EXECUTOR.submit(fn, *args, ctx=ctx, **kwargs).result()
    wrapper.__name__ = fn.__name__
    return wrapper


@tool("browser_open", "Abrir um endereço no navegador controlado pela Viv.", {"url": {"type": "string"}},
      title="Navegador")
@_on_browser_thread
def browser_open(url, ctx=None):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    page = _page(ctx)
    page.goto(url, wait_until="domcontentloaded")
    return f"aberto {page.url}: {page.title()[:160]}"


@tool("browser_search", "Pesquisar no Google dentro do navegador controlado pela Viv.",
      {"query": {"type": "string"}}, title="Pesquisa no navegador")
@_on_browser_thread
def browser_search(query, ctx=None):
    page = _page(ctx)
    page.goto("https://www.google.com/search?q=" + quote_plus(query), wait_until="domcontentloaded")
    return f"resultados prontos para {query}"


@tool("browser_extract", "Extrair o texto legível da página atual do navegador.",
      {"selector": {"type": "string", "required": False}, "max_chars": {"type": "integer", "required": False}},
      title="Lendo página")
@_on_browser_thread
def browser_extract(selector=None, max_chars=6000, ctx=None):
    text = _page(ctx).locator(selector or "body").first.inner_text()
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:int(max_chars)]


@tool("browser_click", "Clicar num elemento da página pelo texto, nome acessível ou seletor CSS.",
      {"target": {"type": "string"}}, title="Clique na página")
@_on_browser_thread
def browser_click(target, ctx=None):
    page = _page(ctx)
    for locate in (lambda: page.get_by_role("button", name=target, exact=False),
                   lambda: page.get_by_role("link", name=target, exact=False),
                   lambda: page.get_by_text(target, exact=False)):
        try:
            locate().first.click(timeout=4000)
            return f"clicado {target}"
        except Exception:
            continue
    page.locator(target).first.click(timeout=4000)
    return f"clicado {target}"


@tool("browser_type", "Preencher um campo da página pelo rótulo, placeholder ou seletor CSS.",
      {"target": {"type": "string"}, "text": {"type": "string"}}, title="Preenchendo campo")
@_on_browser_thread
def browser_type(target, text, ctx=None):
    page = _page(ctx)
    for locate in (lambda: page.get_by_label(target, exact=False),
                   lambda: page.get_by_placeholder(target, exact=False)):
        try:
            locate().first.fill(text, timeout=4000)
            return f"preenchido {target}"
        except Exception:
            continue
    page.locator(target).first.fill(text, timeout=4000)
    return f"preenchido {target}"


@tool("browser_press", "Pressionar uma tecla na página atual, ex.: Enter.", {"key": {"type": "string"}},
      title="Tecla na página")
@_on_browser_thread
def browser_press(key, ctx=None):
    _page(ctx).keyboard.press(key)
    return f"pressionado {key}"


@tool("browser_new_tab", "Abrir uma nova aba, opcionalmente já num endereço.",
      {"url": {"type": "string", "required": False}}, title="Nova aba")
@_on_browser_thread
def browser_new_tab(url=None, ctx=None):
    _page(ctx)
    page = _STATE["context"].new_page()
    if url:
        page.goto(url if url.startswith(("http://", "https://")) else "https://" + url,
                  wait_until="domcontentloaded")
    _STATE["page"] = page
    return f"nova aba {page.url}"


@tool("browser_tabs", "Listar as abas abertas no navegador controlado pela Viv.", {}, title="Abas")
@_on_browser_thread
def browser_tabs(ctx=None):
    _page(ctx)
    return "\n".join(f"{i}: {p.title()[:100]} ({p.url})" for i, p in enumerate(_STATE["context"].pages))


@tool("browser_screenshot", "Salvar uma captura da página atual do navegador.",
      {"path": {"type": "string", "required": False}}, title="Captura da página")
@_on_browser_thread
def browser_screenshot(path="data/browser.png", ctx=None):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _page(ctx).screenshot(path=path, full_page=True)
    return path
