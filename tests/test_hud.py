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


def test_cards_show_a_timer_bar_that_dismisses_them_and_pauses_on_hover(page):
    page.evaluate("window.VivCards.show({text: 'Rápido', kind: 'action', body: 'ok', ok: true})")
    bar = page.locator(".card.toast .card-life i")
    assert bar.count() == 1 and bar.evaluate("n => getComputedStyle(n).animationName") == "life"
    assert bar.evaluate("n => n.style.animationDuration") == "8000ms"
    page.wait_for_timeout(700)
    page.hover(".card.toast")
    assert bar.evaluate("n => getComputedStyle(n).animationPlayState") == "paused"
    first = bar.evaluate("n => n.getBoundingClientRect().width")
    assert first < page.locator(".card.toast .card-life").bounding_box()["width"] - 5   # já encolheu um pouco
    page.wait_for_timeout(400)
    assert abs(bar.evaluate("n => n.getBoundingClientRect().width") - first) < 1      # parado enquanto o mouse está em cima
    page.mouse.move(640, 700)
    assert bar.evaluate("n => getComputedStyle(n).animationPlayState") == "running"
    bar.evaluate("n => { n.style.animationDuration = '300ms'; }")
    page.wait_for_timeout(1200)
    assert page.locator(".card.toast").count() == 0                                    # o fim da barra tira o cartão


def test_panel_has_timer_bar_pinned_to_its_bottom_edge(page):
    emit(page, channel="card", text="Longo", kind="content", body="linha\n\n" * 80, ok=True)
    page.wait_for_timeout(900)
    panel = page.locator(".card.panel").bounding_box()
    life = page.locator(".card.panel .card-life").bounding_box()
    assert page.locator(".card.panel .card-life i").evaluate("n => n.style.animationDuration") == "75000ms"
    assert abs((life["y"] + life["height"]) - (panel["y"] + panel["height"])) <= 2      # visível mesmo com rolagem


def test_text_panel_formats_markdown_without_parsing_html(page):
    body = ("# Título\n## Seção\nTexto com **negrito**, *itálico*, `código` e [link](https://example.com/a) "
            "e [ruim](javascript:alert(1)).\n\n- um\n- [x] feito\n- [ ] a fazer\n\n1. primeiro\n2. segundo\n\n"
            "> destaque\n\nNome | Valor\n--- | ---\nA | **1**\n\n```\nprint('<b>oi</b>')\n```\n<img src=x onerror=window.__xss=1>")
    emit(page, channel="card", text="Formatado", kind="content", body=body, ok=True)
    md = page.locator(".card.panel .md")
    assert md.locator("h4.md-h1").inner_text() == "Título" and md.locator("h4.md-h2").inner_text() == "Seção"
    assert md.locator("p strong").first.inner_text() == "negrito" and md.locator("p em").inner_text() == "itálico"
    assert md.locator("p code").inner_text() == "código"
    links = md.locator("a")
    assert links.count() == 1 and links.first.get_attribute("href") == "https://example.com/a"
    assert md.locator("ul li").count() == 3 and md.locator("li.todo[data-done='true']").inner_text() == "feito"
    assert md.locator("ol li").count() == 2 and md.locator("blockquote").inner_text() == "destaque"
    assert md.locator("table tr").count() == 2 and md.locator("td strong").inner_text() == "1"
    assert md.locator("pre code").inner_text() == "print('<b>oi</b>')"
    assert page.locator(".card img, .card b").count() == 0 and page.evaluate("window.__xss") is None
    assert page.errors == []


def test_toast_body_gets_inline_formatting_only(page):
    emit(page, channel="card", text="Ação", kind="action", body="salvo em `C:/x.txt` com **sucesso**", ok=True)
    assert page.locator(".card.toast .card-body code").inner_text() == "C:/x.txt"
    assert page.locator(".card.toast .card-body strong").inner_text() == "sucesso"


def test_progress_bar_shows_only_for_tasks_that_take_a_while(page):
    emit(page, channel="progress", text="Abrindo aplicativo", value=None, done=False)
    emit(page, channel="progress", text="", value=None, done=True)
    page.wait_for_timeout(1100)
    assert page.is_hidden("#progress"), "ação rápida não pode piscar a barra"
    emit(page, channel="progress", text="Pesquisa profunda", value=None, done=False)
    emit(page, channel="progress", text="Lendo a fonte 2 de 4", value=0.5, done=False)
    page.wait_for_timeout(1100)
    assert page.is_visible("#progress") and page.inner_text("#progress-label") == "Lendo a fonte 2 de 4"
    assert "0.5" in page.evaluate("document.getElementById('progress-fill').style.transform")
    box = page.locator("#progress").bounding_box()
    assert box["height"] < 40 and box["y"] > 400, "discreta, junto ao rodapé"
    emit(page, channel="progress", text="", value=None, done=True)
    assert page.is_hidden("#progress")


def test_mood_recolors_the_hud_and_shows_its_name(page):
    emit(page, channel="mood", text="Irritada", name="irritada", palette=["#ff5a4d", "#c23b6b", "#ff9a4d"], enabled=True)
    assert page.text_content("#mood") == "Irritada" and page.is_visible("#mood")
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--viv-rose').trim()") == "#ff5a4d"
    emit(page, channel="mood", text="Serena", name="serena", palette=["#ff5fa8", "javascript:1", "#5fe6ff"], enabled=False)
    assert page.is_hidden("#mood")
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--viv-rose').trim()") == "#ff5a4d", \
        "paleta inválida é ignorada"
    assert page.errors == []


def test_speaker_chip_names_who_is_talking_and_clears_on_sleep(page):
    emit(page, channel="speaker", text="Gabriel", known=True, owner=True)
    assert page.text_content("#who") == "Gabriel"
    emit(page, channel="speaker", text="", known=False, owner=False)
    assert page.text_content("#who") == "voz não reconhecida" and page.get_attribute("#who", "data-known") == "false"
    emit(page, channel="state", state="sleeping")
    assert page.is_hidden("#who")


CHATS = [{"name": "Maria Silva", "label": "Mãe", "last": "Chegou bem, filho?", "unread": 2, "photo": ""},
         {"name": "Carlos Souza", "label": "o chefe", "last": "Reunião às 9", "unread": 1, "photo": "javascript:alert(1)"},
         {"name": "Grupo da Família", "label": "Grupo da Família", "last": "foto", "unread": 0, "photo": ""}]


def test_whatsapp_spotlights_each_person_as_viv_mentions_them_then_shows_everything(page):
    emit(page, channel="whatsapp", text="WhatsApp", mode="lista", chats=CHATS)
    emit(page, channel="state", state="speaking")
    assert page.locator(".wa-card").count() == 0, "nada aparece antes de ela falar de alguém"
    emit(page, channel="transcript", text="Sua mãe perguntou se você chegou bem.", role="viv", final=False)
    page.wait_for_selector(".wa-spot.in")
    assert "Mãe" in page.text_content(".wa-spot") and "Chegou bem, filho?" in page.text_content(".wa-spot")
    assert "2 mensagens novas" in page.text_content(".wa-spot") and "Reunião" not in page.text_content("#wa")
    emit(page, channel="transcript", text="Sua mãe perguntou se você chegou bem. E o chefe marcou reunião às nove.", role="viv", final=False)
    page.wait_for_timeout(700)
    assert page.locator(".wa-spot.in").count() == 1 and "o chefe" in page.text_content(".wa-spot.in")
    emit(page, channel="state", state="listening")
    page.wait_for_selector(".wa-list.in")
    page.wait_for_timeout(600)
    assert page.locator(".wa-row").count() == 3 and page.locator('.wa-row[data-pending="true"]').count() == 2
    assert "2 conversas pendentes" in page.text_content(".wa-list") and page.locator(".wa-badge").count() == 2
    assert page.locator("#wa img").count() == 0, "endereço de foto que não é https do WhatsApp é ignorado"
    page.click(".wa-close")
    page.wait_for_timeout(600)
    assert page.locator(".wa-card").count() == 0 and page.errors == []


def test_whatsapp_chat_opens_with_bubbles_photos_and_audio_and_never_parses_html(page):
    pixel = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    messages = [{"out": False, "autor": "Maria Silva", "hora": "14:02", "texto": "<img src=x onerror=window.__wa=1>", "audio": False, "imagem": ""},
                {"out": False, "autor": "Maria Silva", "hora": "14:03", "texto": "", "audio": True, "imagem": ""},
                {"out": False, "autor": "Maria Silva", "hora": "14:04", "texto": "olha a foto", "audio": False, "imagem": pixel},
                {"out": False, "autor": "Maria Silva", "hora": "14:05", "texto": "outra", "audio": False, "imagem": "https://evil.example/x.png"},
                {"out": True, "autor": "Você", "hora": "14:06", "texto": "Tudo certo!", "audio": False, "imagem": ""}]
    emit(page, channel="whatsapp", text="Mãe", mode="chat", contact="Maria Silva", messages=messages)
    page.wait_for_selector(".wa-chat.in")
    page.wait_for_timeout(900)
    assert page.locator(".wa-bubble.in").count() == 4 and page.locator(".wa-bubble.out").count() == 1
    assert page.locator(".wa-photo").count() == 1 and page.locator(".wa-audio").count() == 1
    assert page.evaluate("window.__wa") is None and "<img src=x" in page.text_content(".wa-thread")
    assert page.text_content(".wa-chat .wa-who b") == "Mãe" and "14:06" in page.text_content(".wa-bubble.out")
    box, core = page.locator(".wa-chat").bounding_box(), page.evaluate("window.VivCore.center()")
    assert box["x"] + box["width"] < core["x"] - core["r"] * .6, "a conversa não cobre o núcleo"
    emit(page, channel="state", state="sleeping")
    page.wait_for_timeout(600)
    assert page.locator(".wa-card").count() == 0 and page.errors == []


def test_whatsapp_connect_card_shows_qr_or_code_and_closes_when_connected(page):
    qr = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    emit(page, channel="whatsapp", text="Conectar WhatsApp", mode="conectar", qr=qr)
    page.wait_for_selector(".wa-connect.in .wa-qr")
    emit(page, channel="whatsapp", text="Conectar WhatsApp", mode="conectar", qr=qr.replace("A60e6", "A60e7"))
    assert page.locator(".wa-connect").count() == 1, "QR renovado troca a imagem, não abre outro cartão"
    emit(page, channel="whatsapp", text="WhatsApp conectado", mode="conectado")
    page.wait_for_timeout(600)
    assert page.locator(".wa-card").count() == 0
    emit(page, channel="whatsapp", text="Conectar WhatsApp", mode="conectar", code="ABCD-1234")
    page.wait_for_selector(".wa-connect.in")
    assert page.text_content(".wa-code") == "ABCD-1234"
    emit(page, channel="whatsapp", text="Conectar WhatsApp", mode="conectar", qr="https://evil.example/qr.png")
    page.wait_for_timeout(300)
    assert page.locator("#wa img").count() == 0 and page.errors == []


def test_spotlight_follows_whole_names_not_a_shared_first_word(page):
    chats = [{"name": "Maria Silva", "label": "Mãe", "aliases": ["Mãe", "Maria Silva", "Maria"], "last": "Me liga",
              "unread": 1, "photo": "", "novas": [{"autor": "", "texto": "Me liga quando puder", "hora": "09:10"}]},
             {"name": "Ana Beatriz Lima", "label": "Minha namorada", "aliases": ["Minha namorada", "Ana Beatriz Lima", "Ana"],
              "last": "kkk", "unread": 1, "photo": "", "novas": [{"autor": "", "texto": "saudade", "hora": "09:12"}]},
             {"name": "Família", "label": "Família", "aliases": ["Família"], "group": True, "last": "Tio Zé: foto",
              "unread": 1, "photo": "", "novas": [{"autor": "Tio Zé", "texto": "foto da festa", "hora": "09:00"}]},
             {"name": "Carlos", "label": "Carlos", "aliases": ["Carlos"], "mine": True, "last": "Você: ok", "unread": 0, "photo": ""}]
    emit(page, channel="whatsapp", text="WhatsApp", mode="lista", chats=chats)
    emit(page, channel="state", state="speaking")
    emit(page, channel="transcript", text="Minha nossa, sua mãe pediu para você ligar.", role="viv", final=False)
    page.wait_for_selector(".wa-spot.in")
    assert page.text_content(".wa-spot.in .wa-who b") == "Mãe", "“minha” sozinho não é a namorada"
    assert "Me liga quando puder" in page.text_content(".wa-spot.in")
    emit(page, channel="transcript", text="Minha nossa, sua mãe pediu para você ligar. No grupo Família, o Tio Zé mandou foto.",
         role="viv", final=False)
    page.wait_for_timeout(700)
    spot = page.locator(".wa-spot.in")
    assert "Família" in spot.text_content() and page.text_content(".wa-spot.in .wa-author") == "Tio Zé"
    emit(page, channel="state", state="listening")
    page.wait_for_selector(".wa-list.in")
    assert "Você: ok" in page.text_content(".wa-list") and page.locator(".wa-badge").count() == 3
    opened = []
    page.route("**/api/whatsapp/abrir", lambda route: (opened.append(route.request.post_data_json), route.fulfill(json={"ok": True})))
    page.wait_for_timeout(600)
    page.locator(".wa-row-open").nth(1).click()
    page.wait_for_timeout(300)
    assert opened == [{"contato": "Ana Beatriz Lima"}] and page.errors == []


def test_group_chat_shows_who_wrote_each_message(page):
    messages = [{"out": False, "autor": "Tio Zé", "hora": "09:00", "texto": "foto da festa", "audio": False, "imagem": ""},
                {"out": True, "autor": "Você", "hora": "09:05", "texto": "linda!", "audio": False, "imagem": ""},
                {"out": False, "autor": "Ana", "hora": "09:06", "texto": "kkk", "audio": False, "imagem": ""}]
    emit(page, channel="whatsapp", text="Família", mode="chat", contact="Família", group=True, messages=messages)
    page.wait_for_selector(".wa-chat.in")
    page.wait_for_timeout(700)
    assert page.locator(".wa-author").all_text_contents() == ["Tio Zé", "Ana"]
    emit(page, channel="whatsapp", text="Mãe", mode="chat", contact="Maria Silva", group=False,
         messages=[{"out": False, "autor": "Maria Silva", "hora": "09:00", "texto": "oi", "audio": False, "imagem": ""}])
    page.wait_for_timeout(700)
    assert page.locator(".wa-chat.in .wa-author").count() == 0, "em conversa a dois, não repete o nome"


def test_audio_in_open_chat_plays_or_transcribes_and_message_toast_opens_the_chat(page):
    jid = "5551999990001@s.whatsapp.net"
    posted, opened = [], []
    page.route("**/api/whatsapp/audio", lambda route: (posted.append(route.request.post_data_json),
                                                        route.fulfill(json={"ok": True, "transcricao": "chego às 8"})))
    page.route("**/api/whatsapp/abrir", lambda route: (opened.append(route.request.post_data_json), route.fulfill(json={"ok": True})))
    messages = [{"out": False, "autor": "Cris", "hora": "18:31", "texto": "", "audio": True, "imagem": "", "id": "3EB0AUDIO1",
                 "transcricao": ""},
                {"out": False, "autor": "Cris", "hora": "18:32", "texto": "", "audio": True, "imagem": "", "id": "3EB0AUDIO2",
                 "transcricao": "já ouvido"}]
    emit(page, channel="whatsapp", text="Cris", mode="chat", contact="Cris", jid=jid, group=False, messages=messages)
    page.wait_for_selector(".wa-chat.in")
    assert page.locator(".wa-transcribe").count() == 1, "áudio já transcrito mostra o texto, sem botão"
    assert "já ouvido" in page.text_content(".wa-chat")
    page.click(".wa-transcribe")
    page.wait_for_function("document.querySelector('.wa-heard').textContent === 'chego às 8'")
    page.locator(".wa-play").first.click()
    page.wait_for_timeout(300)
    assert posted == [{"jid": jid, "id": "3EB0AUDIO1", "acao": "transcrever"}, {"jid": jid, "id": "3EB0AUDIO1", "acao": "tocar"}]

    emit(page, channel="card", text="WhatsApp: Cris", kind="action", ok=True, wa=jid, body="Foto nova na conversa com Cris.")
    page.wait_for_selector(".card.toast.clickable.in")
    page.click(".card.toast.clickable")
    page.wait_for_timeout(300)
    assert opened == [{"contato": jid}] and page.errors == []


def test_draft_panel_and_whatsapp_chat_stack_instead_of_overlapping(page):
    messages = [{"out": False, "autor": "Elvis", "hora": f"09:{n:02d}", "texto": f"mensagem {n}", "audio": False,
                 "imagem": ""} for n in range(12)]
    emit(page, channel="whatsapp", text="Elvis", mode="chat", contact="Elvis", group=False, messages=messages)
    page.wait_for_selector(".wa-chat.in")
    emit(page, channel="card", text="Rascunho para Elvis", kind="content", ok=True, body="**Para:** Elvis\n\n> Já te falo")
    page.wait_for_selector(".card.panel.in")
    page.wait_for_timeout(700)
    panel = page.locator(".card.panel").bounding_box()
    chat = page.locator(".wa-chat").bounding_box()
    assert chat["y"] >= panel["y"] + panel["height"], "a conversa fica abaixo do rascunho, não por cima"
    assert page.locator(".wa-chat.in").count() == 1, "abrir o rascunho não fecha a conversa"
    page.click(".panel-close")
    page.wait_for_timeout(700)
    assert page.evaluate("document.getElementById('wa').style.top") == "" and page.errors == []
