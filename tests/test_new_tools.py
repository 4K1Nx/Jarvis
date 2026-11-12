import os
import time

import pytest

from viv.bus import BUS
from viv.tools import apps, optimize, registry, weather
from viv.tools.registry import Context

CFG = {"safety": {"dangerous": []}}
APPS = [
    {"Name": "WhatsApp", "AppID": "5319275A.WhatsAppDesktop!App"},
    {"Name": "WhatsApp Web", "AppID": "Brave._crx_x"},
    {"Name": "Steam", "AppID": "{GUID}\\Steam\\Steam.exe"},
    {"Name": "Steam Support Center", "AppID": "http://support.steampowered.com/"},
    {"Name": "Bloco de notas", "AppID": "Microsoft.WindowsNotepad!App"},
    {"Name": "Google Chrome", "AppID": "Chrome"},
    {"Name": "Visual Studio Code", "AppID": "Microsoft.VisualStudioCode"},
    {"Name": "Configurações", "AppID": "windows.immersivecontrolpanel!App"},
]


@pytest.fixture
def cards(monkeypatch):
    seen = []
    monkeypatch.setattr(BUS, "emit", lambda channel, text="", **extra: seen.append((channel, text, extra)))
    return seen


# ---- aplicativos ---------------------------------------------------------
@pytest.mark.parametrize("query,expected", [
    ("whatsapp", "WhatsApp"), ("Steam", "Steam"), ("steam.exe", "Steam"), ("chrome", "Google Chrome"),
    ("bloco de notas", "Bloco de notas"), ("vs code", "Visual Studio Code"), ("vscode", "Visual Studio Code"),
    ("configuracoes", "Configurações"), ("o whatsapp", "WhatsApp"), ("Watsapp", "WhatsApp"),
])
def test_find_app_matches_start_menu_names(query, expected):
    match, _ = apps.find_app(query, APPS)
    assert match and match["Name"] == expected


def test_find_app_returns_suggestions_when_nothing_matches():
    match, suggestions = apps.find_app("photoshop", APPS)
    assert match is None and isinstance(suggestions, list)


def test_launch_uses_start_menu_app_id(monkeypatch, cards):
    started = []
    monkeypatch.setattr(apps, "installed_apps", lambda: APPS)
    monkeypatch.setattr(apps.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    out = registry.call("desktop_launch_app", {"app": "whatsapp"}, Context(CFG))
    assert started == [["explorer.exe", "shell:AppsFolder\\5319275A.WhatsAppDesktop!App"]]
    assert "WhatsApp" in out and not out.startswith("erro")


def test_launch_unknown_app_returns_error_without_starting_anything(monkeypatch, cards):
    started = []
    monkeypatch.setattr(apps, "installed_apps", lambda: APPS)
    monkeypatch.setattr(apps.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    monkeypatch.setattr(apps.os, "startfile", lambda p: started.append(p), raising=False)
    out = registry.call("desktop_launch_app", {"app": "programa-que-nao-existe-xyz"}, Context(CFG))
    assert out.startswith("erro:") and "não encontrado" in out and started == []


def test_list_apps_filters_and_shows_panel(monkeypatch, cards):
    monkeypatch.setattr(apps, "installed_apps", lambda: APPS)
    out = registry.call("desktop_list_apps", {"filtro": "steam"}, Context(CFG))
    assert "Steam" in out and "WhatsApp" not in out
    assert any(ch == "card" and extra.get("kind") == "content" for ch, _, extra in cards)


# ---- clima ---------------------------------------------------------------
PLACE = {"name": "Vila Velha", "admin1": "Espírito Santo", "country": "Brasil"}
FORECAST = {
    "current": {"temperature_2m": 24.3, "apparent_temperature": 26.1, "relative_humidity_2m": 78,
                "weather_code": 61, "wind_speed_10m": 14.2},
    "daily": {"time": ["2026-11-12", "2026-11-13", "2026-11-14"], "weather_code": [61, 2, 0],
              "temperature_2m_max": [26.0, 28.4, 30.1], "temperature_2m_min": [20.2, 21.0, 22.5],
              "precipitation_probability_max": [80, 30, 5]},
}


def test_parse_weather_builds_panel_data():
    w = weather.parse_weather(PLACE, FORECAST)
    assert w["city"] == "Vila Velha, Espírito Santo" and w["temp"] == 24 and w["feels"] == 26
    assert w["desc"] == "Chuva fraca" and w["max"] == 26 and w["min"] == 20 and w["rain"] == 80
    assert w["humidity"] == 78 and w["wind"] == 14
    assert len(w["days"]) == 2 and w["days"][0] == {"label": "sex", "max": 28, "min": 21, "rain": 30, "desc": "Parcialmente nublado"}


def test_weather_tool_emits_weather_card_and_spoken_summary(monkeypatch, cards):
    monkeypatch.setattr(weather, "fetch", lambda cidade, estado=None: (PLACE, FORECAST))
    out = registry.call("web_clima", {"cidade": "Vila Velha"}, Context(CFG))
    assert "24" in out and "Chuva fraca" in out
    card = next(extra for ch, _, extra in cards if ch == "card")
    assert card["kind"] == "weather" and card["weather"]["city"].startswith("Vila Velha")


def test_weather_tool_reports_unknown_city(monkeypatch, cards):
    def missing(cidade, estado=None):
        raise LookupError("cidade não encontrada: Xyzzy")
    monkeypatch.setattr(weather, "fetch", missing)
    assert registry.call("web_clima", {"cidade": "Xyzzy"}, Context(CFG)).startswith("erro:")


# ---- limpeza -------------------------------------------------------------
def make_tree(root):
    old = time.time() - 3 * 86400
    (root / "sub").mkdir()
    files = {"velho.tmp": old, "sub/velho2.log": old, "novo.tmp": time.time()}
    for name, stamp in files.items():
        path = root / name
        path.write_bytes(b"x" * 1000)
        os.utime(path, (stamp, stamp))
    return root


def test_clean_folder_removes_only_files_older_than_a_day(tmp_path):
    root = make_tree(tmp_path)
    freed, count = optimize.clean_folder(str(root), min_age_hours=24)
    assert freed == 2000 and count == 2
    assert (root / "novo.tmp").exists() and not (root / "velho.tmp").exists() and not (root / "sub" / "velho2.log").exists()


def test_clean_folder_ignores_missing_folder_and_locked_files(tmp_path, monkeypatch):
    assert optimize.clean_folder(str(tmp_path / "nao-existe")) == (0, 0)
    root = make_tree(tmp_path)

    def locked(path):
        raise PermissionError("em uso")
    monkeypatch.setattr(optimize.os, "remove", locked)
    assert optimize.clean_folder(str(root)) == (0, 0)


def test_folder_size_counts_bytes(tmp_path):
    make_tree(tmp_path)
    assert optimize.folder_size(str(tmp_path)) == 3000


def test_cleanup_is_dangerous_and_diagnostic_is_not():
    registry.load_all()
    assert registry.is_dangerous("system_limpeza", CFG) is True
    assert registry.is_dangerous("system_diagnostico", CFG) is False


def test_cleanup_reports_freed_space(monkeypatch, tmp_path, cards):
    root = make_tree(tmp_path)
    monkeypatch.setattr(optimize, "cleanup_targets", lambda: [("Temporários", str(root))])
    monkeypatch.setattr(optimize, "empty_recycle_bin", lambda: True)
    monkeypatch.setattr(optimize, "flush_dns", lambda: True)
    out = registry.call("system_limpeza", {}, Context(CFG))
    assert "2 arquivo" in out and not (root / "velho.tmp").exists()
    assert any(ch == "card" and extra.get("kind") == "content" for ch, _, extra in cards)


# ---- pesquisa ------------------------------------------------------------
def test_search_shows_results_panel_and_opens_requested_tabs(monkeypatch, cards):
    from viv.tools import web
    hits = [{"title": f"Fonte {i}", "url": f"https://example.com/{i}", "body": f"Resumo {i}"} for i in range(4)]
    opened = []
    monkeypatch.setattr(web, "search", lambda query, max_results=5: hits)
    monkeypatch.setattr(web.webbrowser, "open", lambda url, *a, **k: opened.append(url))
    out = registry.call("web_search", {"query": "teste", "abrir_guias": 2}, Context(CFG))
    assert opened == ["https://example.com/0", "https://example.com/1"]
    card = next(extra for ch, _, extra in cards if ch == "card")
    assert card["kind"] == "search" and len(card["results"]) == 4 and card["results"][0]["body"] == "Resumo 0"
    assert "Fonte 0" in out


def test_search_never_opens_non_http_links(monkeypatch, cards):
    from viv.tools import web
    opened = []
    monkeypatch.setattr(web, "search", lambda query, max_results=5: [{"title": "x", "url": "file:///c:/x", "body": ""}])
    monkeypatch.setattr(web.webbrowser, "open", lambda url, *a, **k: opened.append(url))
    registry.call("web_search", {"query": "teste", "abrir_guias": 3}, Context(CFG))
    assert opened == []
