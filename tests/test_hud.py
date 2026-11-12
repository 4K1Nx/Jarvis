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
    import tempfile
    from viv.settings import Settings
    settings = Settings(tempfile.mkdtemp() + "/cfg.json", {})
    server = uvicorn.Server(uvicorn.Config(create_app(viv, gate, FakeAudio(), cfg, FakeSpeaker(), settings),
                                           host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    viv.settings = settings
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


def test_action_cards_are_toasts_and_only_four_stay(page):
    emit(page, channel="card", text="Abrindo aplicativo: notepad", kind="action", body="notepad aberto", ok=True)
    assert page.locator(".card").count() == 1
    for i in range(6):
        emit(page, channel="card", text=f"Cartão {i}", kind="action", body="ok", ok=True)
    page.wait_for_timeout(600)
    assert page.locator(".card.toast:not(.out)").count() == 4


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


def test_panel_and_toasts_do_not_overlap_each_other_or_the_core(page):
    emit(page, channel="card", text="Lista", kind="content", format="lista", body="item\n" * 40, ok=True)
    for i in range(4):
        emit(page, channel="card", text=f"Ação {i}", kind="action", body="resultado " * 20, ok=True)
    page.wait_for_timeout(700)
    boxes = [b.bounding_box() for b in page.locator(".card").all()]
    assert len(boxes) == 5
    core = page.evaluate("window.VivCore.center()")

    def overlap(a, b):
        return not (a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"]
                    or a["y"] + a["height"] <= b["y"] or b["y"] + b["height"] <= a["y"])
    assert not any(overlap(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:])
    r = core["r"] / 1.6
    orb = {"x": core["x"] - r, "y": core["y"] - r, "width": 2 * r, "height": 2 * r}
    assert not any(overlap(orb, b) for b in boxes)
    assert all(b["y"] + b["height"] <= 800 - 190 for b in boxes)


def test_new_panel_replaces_previous_and_close_button_removes_it(page):
    emit(page, channel="card", text="Primeiro", kind="content", body="a", ok=True)
    emit(page, channel="card", text="Segundo", kind="content", body="b", ok=True)
    page.wait_for_timeout(600)
    assert page.locator(".card.panel:not(.out)").count() == 1
    assert "Segundo" in page.inner_text(".card.panel:not(.out)")
    page.click(".card.panel:not(.out) .panel-close")
    page.wait_for_timeout(600)
    assert page.locator(".card.panel").count() == 0


def test_weather_panel_shows_temperature_stats_and_days(page):
    emit(page, channel="card", text="Clima em Vila Velha", kind="weather", ok=True, weather={
        "city": "Vila Velha", "temp": 24, "feels": 26, "desc": "Chuva fraca", "max": 26, "min": 20, "rain": 80,
        "humidity": 78, "wind": 14, "days": [{"label": "sex", "max": 28, "min": 21, "rain": 30, "desc": "Nublado"},
                                              {"label": "sáb", "max": 30, "min": 22, "rain": 5, "desc": "Céu limpo"}]})
    text = page.inner_text(".card.panel")
    assert "24°" in text and "Chuva fraca" in text and "80%" in text and "14 km/h" in text
    assert page.locator(".weather-day").count() == 2


def test_search_panel_lists_results_with_snippets_and_safe_links(page):
    emit(page, channel="card", text="Pesquisa: teste", kind="search", ok=True, results=[
        {"title": "Fonte A", "url": "https://www.example.com/a", "body": "Resumo da fonte A"},
        {"title": "<b>Fonte B</b>", "url": "https://example.org/b", "body": "<script>window.__xss=1</script>"},
        {"title": "Ruim", "url": "javascript:alert(1)", "body": "x"}])
    assert page.locator(".result").count() == 2
    assert page.locator(".result-title").first.get_attribute("href") == "https://www.example.com/a"
    assert "example.com" in page.locator(".result-host").first.inner_text()
    assert "Resumo da fonte A" in page.inner_text(".card.panel") and page.evaluate("window.__xss") is None
    assert page.locator(".card.panel b, .card.panel script").count() == 0


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
    assert page.locator(".card.toast:not(.out)").count() == 3


def test_settings_drawer_opens_edits_and_closes(site, page):
    _, viv, _ = site
    page.click("#gear")
    page.wait_for_selector("#settings.open .setting")
    assert page.locator("#settings .setting").count() >= 10
    name = page.locator('#settings input[data-key="usuario.nome"]')
    name.fill("João"); name.press("Tab")
    for _ in range(100):
        if viv.settings.get("usuario.nome") == "João":
            break
        page.wait_for_timeout(20)
    assert viv.settings.get("usuario.nome") == "João"
    page.locator('#settings input[data-key="audio.fones"]').check()
    page.wait_for_timeout(300)
    assert viv.settings.get("audio.fones") is True
    page.fill("#routine-time", "07:30"); page.fill("#routine-text", "Academia"); page.click("#routine-form button")
    page.wait_for_selector(".routine-row")
    assert "Academia" in page.inner_text("#routine-list") and viv.settings.routine()[0]["hora"] == "07:30"
    page.click(".routine-remove")
    page.wait_for_selector(".routine-empty")
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    assert not page.is_visible("#settings") and page.errors == []


def test_invalid_setting_shows_error_message(page):
    page.click("#gear")
    page.wait_for_selector("#settings.open .setting")
    field = page.locator('#settings input[data-key="conversa.segundos_ate_dormir"]')
    field.fill("3"); field.press("Tab")
    page.wait_for_selector("#settings-msg.bad")
    assert "entre 15 e 600" in page.inner_text("#settings-msg")


def test_panels_and_toasts_open_with_animation(page):
    emit(page, channel="card", text="Lista", kind="content", format="lista", body="a\nb\nc", ok=True)
    emit(page, channel="card", text="Ação", kind="action", body="ok", ok=True)
    page.wait_for_selector(".card.panel.in"); page.wait_for_selector(".card.toast.in")
    assert page.evaluate("getComputedStyle(document.querySelector('.card.panel.in')).animationName") == "panel-in"
    assert page.evaluate("getComputedStyle(document.querySelector('.card.toast.in')).animationName") == "toast-in"
    assert page.evaluate("getComputedStyle(document.querySelector('.card.panel.in li')).animationName") == "reveal"
    page.wait_for_timeout(1300)
    assert page.evaluate("getComputedStyle(document.querySelector('.card.panel.in')).opacity") == "1"
    page.click(".panel-close")
    assert page.evaluate("getComputedStyle(document.querySelector('.card.panel.out')).animationName") == "panel-out"


def test_reduced_motion_disables_card_animations(site, browser):
    url, _, _ = site
    context = browser.new_context(reduced_motion="reduce", viewport={"width": 1280, "height": 800})
    p = context.new_page(); p.goto(url); p.wait_for_function("window.VivHUD")
    p.evaluate("e => window.VivHUD.handle(e)", {"channel": "card", "text": "Lista", "kind": "content", "body": "a", "ok": True})
    p.wait_for_selector(".card.panel.in")
    assert p.evaluate("getComputedStyle(document.querySelector('.card.panel.in')).animationName") == "none"
    assert p.evaluate("getComputedStyle(document.querySelector('.card.panel.in')).opacity") == "1"
    context.close()


def test_confirm_without_voice_enrollment_tells_user_to_click(page):
    emit(page, channel="confirm", text="Limpar o PC", name="system_limpeza", args={}, seconds=30, voice=False)
    assert "Clique em Sim" in page.inner_text(".confirm") and "Limpar o PC" in page.inner_text(".confirm")
