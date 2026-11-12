"""HUD num navegador real (Chromium headless) contra o servidor com objetos falsos."""
import socket
import threading
import time

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

from server import create_app  # noqa: E402
from tests.test_server import FakeAudio, FakeGate, FakeSpeaker, FakeViv  # noqa: E402


@pytest.fixture(scope="module")
def site():
    import uvicorn
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    viv, gate = FakeViv(), FakeGate()
    cfg = {"server": {"host": "127.0.0.1", "port": port}, "live": {"model": "m"}, "tools": {"vision": {}}}
    server = uvicorn.Server(uvicorn.Config(create_app(viv, gate, FakeAudio(), cfg, FakeSpeaker()),
                                           host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}", viv, gate
    server.should_exit = True


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium do Playwright indisponível: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(site, browser):
    url, viv, gate = site
    gate.clicks.clear(); viv.calls.clear()
    p = browser.new_page(viewport={"width": 1280, "height": 800})
    p.errors = []
    p.on("console", lambda m: p.errors.append(m.text) if m.type == "error" else None)
    p.on("pageerror", lambda e: p.errors.append(str(e)))
    p.goto(url)
    p.wait_for_function("window.VivHUD && window.VivCore && window.VivCards")
    yield p
    p.close()


def emit(page, **event):
    page.evaluate("e => window.VivHUD.handle(e)", event)


def test_page_loads_without_console_errors(page):
    page.wait_for_timeout(300)
    assert page.errors == []


def test_state_event_updates_body_and_label(page):
    emit(page, channel="state", state="listening")
    assert page.get_attribute("body", "data-state") == "listening"
    assert page.inner_text("#state-label").strip().lower() == "ouvindo"
    assert page.inner_text("#wake").strip().lower() == "dormir"


def test_card_event_creates_card_and_only_five_stay(page):
    emit(page, channel="card", text="Abrindo aplicativo: notepad", kind="action", body="notepad aberto", ok=True)
    assert page.locator(".card").count() == 1
    for i in range(6):
        emit(page, channel="card", text=f"Cartão {i}", kind="action", body="ok", ok=True)
    page.wait_for_timeout(600)
    assert page.locator(".card:not(.out)").count() == 5


def test_card_text_is_never_parsed_as_html(page):
    payload = "<img src=x onerror=window.__xss=1>"
    emit(page, channel="card", text=payload, kind="content", body=payload, format="lista", ok=True)
    page.wait_for_timeout(200)
    assert page.locator(".card img").count() == 0
    assert page.evaluate("window.__xss") is None
    assert payload in page.inner_text(".card")


def test_search_card_links_only_http_sources(page):
    emit(page, channel="card", text="Pesquisa", kind="search", body="resumo", ok=True, sources=[
        {"title": "Fonte boa", "url": "https://example.com/a"}, {"title": "Fonte ruim", "url": "javascript:alert(1)"}])
    links = page.locator(".card-sources a")
    assert links.count() == 1 and links.first.get_attribute("href") == "https://example.com/a"
    assert "noopener" in links.first.get_attribute("rel")


def test_content_table_renders_rows(page):
    emit(page, channel="card", text="Tabela", kind="content", format="tabela", body="Nome | Valor\nA | 1\nB | 2", ok=True)
    assert page.locator(".card table tr").count() == 3 and page.locator(".card th").count() == 2


def test_cards_do_not_overlap_each_other_or_the_core(page):
    for i in range(5):
        emit(page, channel="card", text=f"Cartão {i}", kind="content", body="linha\n" * 12, ok=True)
    page.wait_for_timeout(700)
    boxes = [b.bounding_box() for b in page.locator(".card").all()]
    core = page.evaluate("window.VivCore.center()")

    def overlap(a, b):
        return not (a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"]
                    or a["y"] + a["height"] <= b["y"] or b["y"] + b["height"] <= a["y"])
    assert not any(overlap(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:])
    r = core["r"] / 1.6
    orb = {"x": core["x"] - r, "y": core["y"] - r, "width": 2 * r, "height": 2 * r}
    assert not any(overlap(orb, b) for b in boxes)


def test_confirm_card_posts_decision_and_is_removed(site, page):
    _, _, gate = site
    emit(page, channel="confirm", text="Apagar: C:/tmp/x.txt", name="fs_delete", args={}, seconds=30)
    assert page.locator(".confirm button").count() == 2
    emit(page, channel="confirm_hint", text="Voz não reconhecida. Confirme na tela.")
    assert "Voz não reconhecida" in page.inner_text(".confirm")
    page.click(".confirm button.yes")
    for _ in range(100):
        if gate.clicks:
            break
        page.wait_for_timeout(20)
    assert gate.clicks == [True]
    emit(page, channel="confirm_done", ok=True)
    assert page.locator(".confirm").count() == 0


def test_wake_button_calls_server(site, page):
    _, viv, _ = site
    page.click("#wake")
    for _ in range(100):
        if viv.calls:
            break
        page.wait_for_timeout(20)
    assert viv.calls == [("wake", "button")]


def test_transcript_updates_captions(page):
    emit(page, channel="transcript", text="que horas são", role="user", final=True)
    emit(page, channel="transcript", text="São três horas.", role="viv", final=False)
    assert page.inner_text("#caption-user") == "que horas são"
    assert page.inner_text("#caption-viv") == "São três horas."


def test_narrow_viewport_has_no_horizontal_scroll(page):
    page.set_viewport_size({"width": 400, "height": 760})
    for i in range(4):
        emit(page, channel="card", text=f"Cartão com um título bem comprido número {i}", kind="action", body="ok", ok=True)
    page.wait_for_timeout(500)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.locator(".card:not(.out)").count() == 3
