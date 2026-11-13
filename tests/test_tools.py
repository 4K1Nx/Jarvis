import re
import pytest
from viv.bus import BUS
from viv.tools import registry
from viv.tools.registry import Context

CFG = {"safety": {"dangerous": []}, "tools": {"vision": {"screenshot_path": "data/screen.png"}}}
EXPECTED = {
    "desktop_launch_app", "desktop_list_apps", "desktop_type_text", "system_programas", "system_desinstalar",
    "tela_vigiar", "tela_parar_vigia", "tela_vigia_status", "email_listar", "email_buscar", "email_ler",
    "config_ver", "config_definir", "rotina_adicionar", "rotina_remover", "rotina_listar", "viv_erros", "system_eventos_erro", "desktop_hotkey", "desktop_click", "desktop_screenshot",
    "desktop_run_command",
    "system_volume", "system_status", "system_processes", "system_power", "system_cancel_shutdown", "system_kill",
    "files_find", "files_open", "files_recent", "files_read_text", "files_create_text", "files_append_text",
    "files_replace_text", "files_move", "fs_list", "fs_read", "fs_write", "fs_delete", "fs_copy", "fs_mkdir",
    "codigo_criar", "codigo_executar", "codigo_parar", "codigo_projetos", "codigo_abrir", "codigo_desfazer",
    "documento_criar", "documento_ler", "pesquisa_profunda",
    "habilidade_salvar", "habilidade_remover", "habilidade_listar", "viv_diagnostico",
    "pessoa_definir", "pessoa_listar", "pessoa_esquecer", "voz_quem_fala",
    "whatsapp_conversas", "whatsapp_ler", "whatsapp_enviar", "whatsapp_abrir", "whatsapp_audio", "whatsapp_conectar", "whatsapp_desconectar",
    "trecho_colado", "mensagem_preparar", "mensagem_rascunhar", "mensagem_copiar", "mensagem_cancelar", "pessoa_estilo",
    "consentimento_registrar", "consentimento_revogar", "relacoes_ver", "relacoes_apagar", "retomar_marcar",
    "retomar_resolver", "presente_salvar", "pessoa_aniversario", "lista_guardar", "encontro_planejar",
    "evento_guardar", "gesto_configurar",
    "browser_open", "browser_search", "browser_extract", "browser_click", "browser_type", "browser_press",
    "browser_new_tab", "browser_tabs", "browser_screenshot",
    "web_search", "web_open", "web_clima", "system_diagnostico", "system_limpeza", "vision_analyze_screen", "hud_mostrar",
}
ASSISTANT = {"memory_lembrar", "memory_esquecer", "reminder_set", "reminder_list"}


@pytest.fixture(autouse=True)
def loaded():
    registry.load_all()


@pytest.fixture
def cards(monkeypatch):
    seen = []
    monkeypatch.setattr(BUS, "emit", lambda channel, text="", **extra: seen.append((channel, text, extra)))
    return seen


def test_load_all_registers_expected_names():
    names = {d["name"] for d in registry.declarations()}
    assert names - ASSISTANT == EXPECTED


def test_names_use_only_lowercase_and_underscore():
    assert all(re.fullmatch(r"[a-z_]+", d["name"]) for d in registry.declarations())


def test_text_file_roundtrip(tmp_path):
    ctx, p = Context(CFG), str(tmp_path / "nota.txt")
    registry.call("files_create_text", {"path": p, "text": "olá"}, ctx)
    assert "olá" in registry.call("files_read_text", {"path": p}, ctx)
    assert "nota.txt" in registry.call("fs_list", {"path": str(tmp_path)}, ctx)
    registry.call("fs_delete", {"path": p}, ctx)
    assert not (tmp_path / "nota.txt").exists()


def test_hud_mostrar_emits_content_card(cards):
    registry.call("hud_mostrar", {"titulo": "Lista", "conteudo": "a\nb", "tipo": "lista"}, Context(CFG))
    assert any(ch == "card" and extra.get("kind") == "content" and text == "Lista" for ch, text, extra in cards)


def test_system_status_reports_cpu_and_ram():
    out = registry.call("system_status", {}, Context(CFG)).lower()
    assert "cpu" in out and "ram" in out
