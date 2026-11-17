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
    assert page.locator(".result").first.get_attribute("href") == "https://www.example.com/a"
    assert page.locator(".result.lead").count() == 1 and page.locator(".result-n").last.inner_text() == "2"
    assert "example.com" in page.locator(".result-host").first.inner_text()
    assert "Resumo da fonte A" in page.inner_text(".card.panel") and page.evaluate("window.__xss") is None
    assert page.locator(".card.panel b, .card.panel script").count() == 0


def test_confirm_card_posts_decision_and_is_removed(site, page):
    _, _, gate = site
    emit(page, channel="state", state="speaking")              # ela já está falando o pedido: o cartão entra na hora
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
    p.evaluate("() => { document.documentElement.dataset.motion = ''; }")      # “Animações completas” desligado
    p.evaluate("e => window.VivHUD.handle(e)", {"channel": "card", "text": "Lista", "kind": "content", "body": "a", "ok": True})
    p.wait_for_selector(".card.panel.in")
    assert p.evaluate("getComputedStyle(document.querySelector('.card.panel.in')).animationName") == "none"
    assert p.evaluate("getComputedStyle(document.querySelector('.card.panel.in')).opacity") == "1"
    context.close()


def test_confirm_without_voice_enrollment_tells_user_to_click(page):
    emit(page, channel="state", state="speaking")
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


def test_pixel_avatar_follows_state_and_mood_and_can_be_hidden(page):
    avatar = page.locator("#avatar")
    assert avatar.is_visible()
    emit(page, channel="state", state="thinking")
    emit(page, channel="mood", text="Brincalhona", name="brincalhona", palette=["#ff6ad5", "#b96bff", "#6bffea"], enabled=True)
    page.wait_for_timeout(300)
    assert avatar.get_attribute("data-state") == "thinking"
    assert avatar.get_attribute("aria-label") == "Viv: pensando, brincalhona"
    lit = page.evaluate("""() => { const c = document.getElementById('avatar-canvas');
        const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0;
        for (let i = 3; i < d.length; i += 4) if (d[i] > 200) n++; return n; }""")
    assert lit > 40, "os olhos e a boca acenderam na telinha"
    emit(page, channel="state", state="executing")
    assert avatar.get_attribute("aria-label").startswith("Viv: lendo")
    emit(page, channel="hud", avatar=False)
    assert not avatar.is_visible()
    emit(page, channel="hud", avatar=True)
    assert avatar.is_visible() and page.errors == []


def test_confirm_card_waits_for_her_voice_but_never_more_than_two_seconds(page):
    emit(page, channel="state", state="thinking")
    emit(page, channel="confirm", text="Apagar pasta", name="fs_delete", args={}, seconds=30)
    assert not page.locator(".confirm").is_visible()            # ela ainda não disse o que vai fazer
    emit(page, channel="state", state="speaking")
    page.wait_for_timeout(250)
    assert page.locator(".confirm").is_visible()
    emit(page, channel="confirm_done", ok=False)
    emit(page, channel="state", state="thinking")
    emit(page, channel="confirm", text="Apagar pasta", name="fs_delete", args={}, seconds=30)
    page.wait_for_timeout(2400)
    assert page.locator(".confirm").is_visible()                # calada, o cartão aparece mesmo assim
    emit(page, channel="confirm_done", ok=False)


def test_questions_stack_in_one_card_with_the_suggestion_marked(page):
    emit(page, channel="ask", text="Tamanho?", options=["Curta", "Média"], suggestion="Média")
    emit(page, channel="ask", text="<b>Tema</b>?", options=["Claro", "Escuro"], suggestion="")
    assert page.locator(".ask-row").count() == 2 and page.locator(".ask button.suggested").inner_text() == "Média"
    assert page.locator(".ask b").count() == 0                  # o texto da pergunta nunca vira HTML
    emit(page, channel="ask_done")
    assert page.locator(".ask").count() == 0


def test_chart_panel_draws_gauges_and_updates_in_place(page):
    chart = {"type": "medidores", "unit": "", "items": [{"label": "CPU", "value": 20, "max": 100, "unit": "%"},
                                                         {"label": "Memória", "value": 50, "max": 100, "unit": "%"}]}
    emit(page, channel="card", text="PC ao vivo", kind="chart", chart=chart, live="pc", ok=True)
    page.wait_for_timeout(900)
    assert page.locator(".gauge").count() == 2 and page.locator(".gauge-value").first.inner_text() == "20%"
    chart["items"][0]["value"] = 80
    emit(page, channel="card", text="PC ao vivo", kind="chart", chart=chart, live="pc", ok=True)
    page.wait_for_timeout(900)
    assert page.locator(".card.panel").count() == 1 and page.locator(".gauge-value").first.inner_text() == "80%"
    emit(page, channel="card", text="Vendas", kind="chart", ok=True,
         chart={"type": "barras", "unit": " MB", "items": [{"label": "<i>a</i>", "value": 3}, {"label": "b", "value": 9}]})
    page.wait_for_timeout(500)
    assert page.locator(".bar-row").count() == 2 and page.locator(".bar-label i").count() == 0


def test_hibernating_shows_its_own_label_and_hides_the_hibernate_button(page):
    emit(page, channel="state", state="sleeping", hibernating=True)
    assert page.inner_text("#state-label") == "Hibernando" and not page.locator("#hibernate").is_visible()
    assert page.locator("#hibernation").is_visible() and "Não estou ouvindo" in page.inner_text("#hibernation")
    page.wait_for_timeout(1100)                                  # o núcleo apaga aos poucos
    assert float(page.evaluate("() => getComputedStyle(document.getElementById('core')).opacity")) < 0.5
    emit(page, channel="state", state="listening", hibernating=False)
    assert page.inner_text("#state-label") == "Ouvindo" and page.locator("#hibernate").is_visible()


LIT = """() => {
  const c = document.getElementById('avatar-canvas'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  let n = 0;                                     // brilho total aceso: os olhos crescem com a voz
  for (let i = 3; i < d.length; i += 4) n += d[i];
  return n;
}"""


def test_avatar_eyes_pulse_with_her_voice_and_settle_in_the_pauses(page):
    emit(page, channel="hud", avatar=True)
    emit(page, channel="state", state="speaking")
    page.wait_for_timeout(1600)                              # passa a carinha de quem acabou de acordar
    sizes = []
    for volume in (0.0, 0.9, 0.0):
        for _ in range(12):                                  # o volume chega 20 vezes por segundo, como no áudio real
            emit(page, channel="level", source="out", value=volume)
            page.wait_for_timeout(50)
        sizes.append(page.evaluate(LIT))
    quiet, loud, pause = sizes
    assert loud > quiet * 1.05 and abs(pause - quiet) < quiet * .05, sizes      # crescem com o som, voltam no silêncio
    emit(page, channel="state", state="listening")


def test_avatar_eyes_follow_the_mouse(page):
    emit(page, channel="hud", avatar=True)
    emit(page, channel="state", state="listening")
    page.wait_for_timeout(1600)
    center = page.evaluate("""() => { const c = document.getElementById('avatar-canvas'), d = c.getContext('2d')
      .getImageData(0, 0, c.width, c.height).data; let sx = 0, n = 0;
      for (let y = 0; y < c.height; y++) for (let x = 0; x < c.width; x++) { const a = d[(y * c.width + x) * 4 + 3]; sx += x * a; n += a; }
      return sx / n / c.width; }""")
    page.mouse.move(1270, 700)                               # bem à direita da telinha
    page.wait_for_timeout(700)
    right = page.evaluate("""() => { const c = document.getElementById('avatar-canvas'), d = c.getContext('2d')
      .getImageData(0, 0, c.width, c.height).data; let sx = 0, n = 0;
      for (let y = 0; y < c.height; y++) for (let x = 0; x < c.width; x++) { const a = d[(y * c.width + x) * 4 + 3]; sx += x * a; n += a; }
      return sx / n / c.width; }""")
    assert right > center + .05, (center, right)

def test_briefing_and_email_panels_are_drawn_without_parsing_html(page):
    emit(page, channel="card", text="Resumo do dia", kind="briefing", ok=True, brief={
        "hora": "08:12", "dia": "segunda-feira", "clima": {"city": "Fortaleza", "temp": 29, "desc": "<b>Sol</b>", "max": 32, "rain": 20},
        "numeros": [{"label": "e-mails não lidos", "value": 7}, {"label": "de disco livre", "value": "8%", "tone": "bad"}],
        "listas": [{"titulo": "Lembretes", "itens": ["<i>Pagar a luz</i>", "Oficina"]}]})
    assert page.inner_text(".brief-when b") == "08:12" and page.locator(".brief-tile").count() == 2
    assert page.locator(".brief-list li").count() == 2 and page.locator(".brief b b, .brief i").count() == 0
    emit(page, channel="card", text="E-mails", kind="content", format="tabela", ok=True, body="x | y",
         emails=[{"n": 1, "de": "Ana <ana@x.com>", "assunto": "<b>Oi</b>", "data": "16/11"}])
    assert page.locator(".mail").count() == 1 and page.inner_text(".mail-from") == "Ana" and page.locator(".mail b b").count() == 0


def test_parallax_moves_the_layers_with_the_pointer(page):
    size = page.viewport_size
    page.mouse.move(size["width"] - 5, size["height"] - 5)
    read = "() => [getComputedStyle(document.documentElement).getPropertyValue('--px'), getComputedStyle(document.getElementById('core')).transform]"
    for _ in range(100):                                        # as camadas chegam ao lado do mouse e os cartões param lá
        shift = page.evaluate(read)
        if float(shift[0] or 0) > 0.9:
            break
        page.wait_for_timeout(100)
    assert float(shift[0]) > 0.9 and shift[1] not in ("none", "matrix(1, 0, 0, 1, 0, 0)")
    px = "() => getComputedStyle(document.documentElement).getPropertyValue('--px')"
    for _ in range(60):                                         # com o mouse parado, os cartões param de se mexer
        still = page.evaluate(px)
        page.wait_for_timeout(300)
        if page.evaluate(px) == still:
            break
    assert page.evaluate(px) == still


def test_buttons_are_styled_and_never_fall_back_to_the_browser_default(page):
    emit(page, channel="state", state="listening", hibernating=False)
    for selector in ("#hibernate", "#chat-open"):
        look = page.evaluate("s => { const c = getComputedStyle(document.querySelector(s)); return [c.backgroundColor, c.color]; }", selector)
        assert look[0] in ("rgba(0, 0, 0, 0)", "transparent") and look[1] != "rgb(0, 0, 0)", (selector, look)
        assert page.inner_text(selector).strip()
    assert "?v=" in page.evaluate("() => document.querySelector('link[rel=stylesheet]').href")


def test_people_in_the_conversation_show_at_the_top(page):
    emit(page, channel="presence", people=["Gabriel"])
    assert not page.locator("#present").is_visible()             # sozinho, nada a mostrar
    emit(page, channel="presence", people=["Gabriel", "<b>Ana</b>", "voz desconhecida 1"])
    emit(page, channel="speaker", text="Gabriel", known=True, owner=True)
    assert page.locator("#present b").count() == 2 and page.inner_text("#present i") == "+1"
    assert page.inner_text("#present b.now") == "Gabriel" and page.locator("#present b b").count() == 0
    emit(page, channel="presence", people=["Gabriel"])
    assert not page.locator("#present").is_visible()


def test_chat_sends_typed_messages_shows_the_conversation_and_switches_mode(site, page):
    _, viv, _ = site
    viv.calls.clear()
    assert not page.locator("#chat").is_visible()
    emit(page, channel="chat", open=True, text_only=False)       # ela abriu o chat a pedido
    assert page.locator("#chat").is_visible()
    page.fill("#chat-input", "oi, <b>Viv</b>")
    page.keyboard.press("Enter")
    for _ in range(100):
        if viv.calls:
            break
        page.wait_for_timeout(20)
    assert viv.calls == [("type", "oi, <b>Viv</b>")]
    emit(page, channel="transcript", text="oi, <b>Viv</b>", role="user", final=True, typed=True)      # o eco não duplica
    emit(page, channel="transcript", text="Oi", role="viv", final=False)
    emit(page, channel="transcript", text="Oi! Tudo bem?", role="viv", final=True)
    emit(page, channel="transcript", text="tudo", role="user", final=True)                             # falado em voz alta
    assert [m.inner_text() for m in page.locator(".chat-msg").all()] == ["oi, <b>Viv</b>", "Oi! Tudo bem?", "tudo"]
    assert page.locator(".chat-msg b").count() == 0
    page.click('.chat-modes [data-mode="texto"]')
    for _ in range(100):
        if viv.text_only:
            break
        page.wait_for_timeout(20)
    assert viv.text_only is True and page.get_attribute('.chat-modes [data-mode="texto"]', "aria-pressed") == "true"
    page.click("#chat-close")                                    # fechar o chat devolve a voz
    for _ in range(100):
        if not viv.text_only:
            break
        page.wait_for_timeout(20)
    assert viv.text_only is False and not page.locator("#chat").is_visible()


def test_chat_can_talk_to_a_local_model_with_its_own_conversation(site, page, monkeypatch):
    from viv.tools import local
    _, viv, _ = site
    monkeypatch.setattr(local, "installed", lambda ctx, http=None: [{"nome": "rpg:8b", "gb": 4.9}])
    monkeypatch.setattr(local, "chat", lambda ctx, model, messages, on_text=None, stream=None: "Você entra na <b>taverna</b>.")
    page.evaluate("() => localStorage.removeItem('viv-chat-modelo')")
    page.click("#chat-open")
    page.wait_for_function("document.querySelectorAll('#chat-model option').length === 2")
    assert not page.locator("#chat-new").is_visible()
    page.select_option("#chat-model", "rpg:8b")
    assert page.locator("#chat-new").is_visible() and page.locator('.chat-modes [data-mode="texto"]').is_disabled()
    viv.calls.clear()
    page.fill("#chat-input", "começa a aventura")
    page.keyboard.press("Enter")
    page.wait_for_function("[...document.querySelectorAll('.chat-msg.viv')].some(m => m.textContent.includes('taverna'))")
    assert [m.inner_text() for m in page.locator(".chat-msg").all()] == ["começa a aventura", "Você entra na <b>taverna</b>."]
    assert viv.calls == [] and page.locator(".chat-msg b").count() == 0
    emit(page, channel="transcript", text="fala da Viv", role="viv", final=True)       # a conversa com a Viv fica na dela
    assert len(page.locator(".chat-msg").all()) == 2
    page.select_option("#chat-model", "viv")
    assert [m.inner_text() for m in page.locator(".chat-msg").all()] == ["fala da Viv"]
    page.select_option("#chat-model", "rpg:8b")
    assert len(page.locator(".chat-msg").all()) == 2
    page.click("#chat-new")
    assert page.locator(".chat-msg").count() == 0
    page.select_option("#chat-model", "viv")
    page.click("#chat-close")
    assert page.errors == []


def test_miniature_shows_only_the_avatar_and_flags_a_pending_confirmation(site, browser):
    url, _, _ = site
    p = browser.new_page(viewport={"width": 184, "height": 136})
    errors = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(url + "/mini?offline")
    p.wait_for_function("window.VivMini && window.VivAvatar")
    assert p.evaluate("() => document.getElementById('avatar-canvas').getBoundingClientRect().width") > 100
    p.evaluate("e => window.VivMini.handle(e)", {"channel": "state", "state": "speaking", "hibernating": False})
    assert p.get_attribute("#avatar", "data-state") == "speaking" and not p.locator("#alert").is_visible()
    p.evaluate("e => window.VivMini.handle(e)", {"channel": "confirm", "text": "Apagar?"})
    assert p.locator("#alert").is_visible()
    p.evaluate("e => window.VivMini.handle(e)", {"channel": "confirm_done", "ok": True})
    p.evaluate("e => window.VivMini.handle(e)", {"channel": "mood", "name": "magoada", "text": "Magoada", "palette": ["#8f8fd6", "#6b5b9b", "#b0a8e8"]})
    p.wait_for_timeout(800)                                  # os olhos abrem com uma mola
    lit = p.evaluate("() => { const c = document.getElementById('avatar-canvas'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 200) n++; return n; }")
    assert lit > 50 and not p.locator("#alert").is_visible() and errors == []
    assert "Magoada".lower() in p.get_attribute("#avatar", "title").lower()
    p.close()


def test_full_animations_keep_the_thinking_eyes_spinning_even_with_windows_in_reduced_mode(site, browser):
    url, _, _ = site
    context = browser.new_context(reduced_motion="reduce", viewport={"width": 280, "height": 200})
    p = context.new_page()
    p.goto(url + "/mini?offline")
    p.wait_for_function("window.VivAvatar")
    frame = """() => { const c = document.getElementById('avatar-canvas'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let h = 0; for (let i = 3; i < d.length; i += 4) h = (h * 31 + (d[i] >> 6)) % 1000000007; return h; }"""
    p.evaluate("() => { document.documentElement.dataset.motion = ''; window.VivAvatar.setState('executing'); }")
    p.wait_for_timeout(3000)                                 # passa o susto de acordar e o anel termina de aparecer
    first = p.evaluate(frame); p.wait_for_timeout(300)
    assert p.evaluate(frame) == first, "sem “Animações completas”, segue o Windows: parado"
    p.evaluate("() => { document.documentElement.dataset.motion = 'full'; }")
    first = p.evaluate(frame); p.wait_for_timeout(300)
    assert p.evaluate(frame) != first, "com “Animações completas”, gira"
    context.close()
