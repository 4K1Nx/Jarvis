"""Caminhos reais, programação, documentos, pesquisa profunda, habilidades e autodiagnóstico."""
import json
import shutil
from pathlib import Path

import pytest

from viv import skills
from viv.bus import BUS
from viv.persona import system_instruction
from viv.tools import _llm, _paths, code, docs, extras, files, registry, research
from viv.tools.registry import Context

CFG = {"safety": {"dangerous": []}}


@pytest.fixture
def cards(monkeypatch):
    seen = []
    monkeypatch.setattr(BUS, "emit", lambda channel, text="", **extra: seen.append((channel, text, extra)))
    return seen


@pytest.fixture
def folders(tmp_path, monkeypatch):
    """Pasta do usuário falsa, com a Área de Trabalho fora do lugar padrão (como faz o OneDrive)."""
    home = tmp_path / "home"
    real = {"desktop": tmp_path / "OneDrive" / "Área de Trabalho", "documents": home / "Documents",
            "downloads": home / "Downloads", "pictures": home / "Pictures"}
    for folder in real.values():
        folder.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    for module in (_paths, code, docs):
        monkeypatch.setattr(module, "known_folder", lambda key: real[key])
    return real


# ---- caminhos --------------------------------------------------------------
@pytest.mark.parametrize("spoken", ["Desktop/notas.txt", "Área de Trabalho/notas.txt", "area de trabalho\\notas.txt",
                                    "~/Desktop/notas.txt"])
def test_resolve_sends_desktop_names_to_the_real_desktop(folders, spoken):
    assert _paths.resolve(spoken) == folders["desktop"] / "notas.txt"


def test_resolve_keeps_existing_and_foreign_paths(folders, tmp_path):
    literal = Path.home() / "Desktop"
    literal.mkdir()
    (literal / "velho.txt").write_text("x", encoding="utf-8")
    assert _paths.resolve(str(literal / "velho.txt")) == literal / "velho.txt"      # existe como escrito
    assert _paths.resolve(str(tmp_path / "outro" / "a.txt")) == tmp_path / "outro" / "a.txt"
    assert _paths.resolve("Downloads") == folders["downloads"]
    assert _paths.resolve("projetos/x") == Path.home() / "projetos" / "x"


def test_recent_and_create_text_accept_spoken_folders(folders):
    (folders["downloads"] / "filme.mkv").write_text("x", encoding="utf-8")
    assert files.recent("Downloads") == "filme.mkv"
    assert "criado" in files.create_text("Desktop/notas.txt", "oi").lower()
    assert (folders["desktop"] / "notas.txt").read_text(encoding="utf-8") == "oi"


def test_move_and_copy_explain_missing_source_and_never_overwrite(folders):
    with pytest.raises(FileNotFoundError, match="files_find"):
        files.move("Desktop/nao-existe.txt", "Documentos")
    (folders["desktop"] / "a.txt").write_text("a", encoding="utf-8")
    assert files.fs_copy("Desktop/a.txt", "Documentos").endswith("a.txt")
    with pytest.raises(FileExistsError):
        files.fs_copy("Desktop/a.txt", "Documentos")
    files.move("Desktop/a.txt", "Documentos/b.txt")
    assert (folders["documents"] / "b.txt").exists() and not (folders["desktop"] / "a.txt").exists()
    assert "pasta pronta" in files.fs_mkdir("Documentos/novo/sub") and (folders["documents"] / "novo" / "sub").is_dir()


# ---- modelo de texto ---------------------------------------------------------
def test_parse_json_accepts_code_fences_and_rejects_garbage():
    assert _llm.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(RuntimeError, match="não consegui ler"):
        _llm.parse_json("claro! aqui está")


def test_ask_without_client_explains():
    with pytest.raises(RuntimeError, match="sem conexão"):
        _llm.ask(Context(CFG), "oi")


# ---- programação -------------------------------------------------------------
def answers(*items):
    queue = list(items)
    return lambda ctx, prompt, as_json=False: queue.pop(0)


def test_build_writes_files_checks_syntax_and_remembers_how_to_run(folders):
    folder = code.project_dir("Jogo da Cobrinha")
    assert folder == folders["documents"] / "Viv" / "Projetos" / "jogo-da-cobrinha"
    folder.mkdir(parents=True)
    result = code.build(None, folder, "um jogo", ask=answers(
        {"resumo": "Feito.", "arquivos": [{"caminho": "main.py", "conteudo": "print('oi')\n"},
                                          {"caminho": "dados/config.json", "conteudo": "{\"a\": 1}"}],
         "executar": "python main.py", "preparar": ""}))
    assert result["arquivos"] == ["main.py", "dados/config.json"] and result["erros"] == []
    assert (folder / "main.py").read_text(encoding="utf-8") == "print('oi')\n"
    assert json.loads((folder / ".viv" / "projeto.json").read_text(encoding="utf-8"))["executar"] == "python main.py"


def test_build_asks_for_a_fix_when_syntax_is_broken(folders, tmp_path):
    folder = tmp_path / "p"
    folder.mkdir()
    result = code.build(None, folder, "x", ask=answers(
        {"resumo": "v1", "arquivos": [{"caminho": "a.py", "conteudo": "def f(:\n"}]},
        {"arquivos": [{"caminho": "a.py", "conteudo": "def f():\n    return 1\n"}]}))
    assert result["erros"] == [] and "return 1" in (folder / "a.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("bad", ["../fora.txt", "C:/Windows/x.txt", "/etc/x", ".git/config", ".viv/projeto.json", ""])
def test_build_refuses_paths_outside_the_project_and_writes_nothing(tmp_path, bad):
    folder = tmp_path / "p"
    folder.mkdir()
    with pytest.raises(ValueError, match="recusado"):
        code.build(None, folder, "x", ask=answers({"arquivos": [{"caminho": "ok.py", "conteudo": "x = 1\n"},
                                                                {"caminho": bad, "conteudo": "x"}]}))
    assert list(folder.iterdir()) == [] and not (tmp_path / "fora.txt").exists()


def test_next_request_shows_existing_files_and_last_run_output(tmp_path):
    folder = tmp_path / "p"
    (folder / ".viv").mkdir(parents=True)
    (folder / "app.py").write_text("print(1/0)\n", encoding="utf-8")
    (folder / ".viv" / "ultima_execucao.txt").write_text("ZeroDivisionError: division by zero", encoding="utf-8")
    seen = []

    def ask(ctx, prompt, as_json=False):
        seen.append(prompt)
        return {"resumo": "ok", "arquivos": [{"caminho": "app.py", "conteudo": "print(1)\n"}]}
    code.build(None, folder, "conserta", ask=ask)
    assert "--- app.py ---" in seen[0] and "ZeroDivisionError" in seen[0] and "conserta" in seen[0]


@pytest.mark.skipif(not shutil.which("git"), reason="git não instalado")
def test_each_step_is_committed_and_can_be_undone(folders, cards):
    folder = code.project_dir("demo")
    folder.mkdir(parents=True)
    code.build(None, folder, "v1", ask=answers({"resumo": "", "arquivos": [{"caminho": "a.txt", "conteudo": "um"}]}))
    code.build(None, folder, "v2", ask=answers({"resumo": "", "arquivos": [{"caminho": "a.txt", "conteudo": "dois"}]}))
    assert code.codigo_desfazer("demo") == "última alteração desfeita"
    assert (folder / "a.txt").read_text(encoding="utf-8") == "um"


def test_codigo_criar_shows_panel_and_cleans_up_when_the_model_fails(folders, cards, monkeypatch):
    monkeypatch.setattr(_llm, "ask", answers({"resumo": "Pronto.", "arquivos": [{"caminho": "index.html", "conteudo": "<h1>oi</h1>"}],
                                              "executar": 'start "" index.html'}))
    text = code.codigo_criar("Página", "uma página", ctx=Context(CFG))
    panel = [c for c in cards if c[2].get("kind") == "content"][-1]
    assert "projeto criado" in text and "codigo_executar" in text and "`index.html`" in panel[2]["body"]

    def boom(ctx, folder, request):
        raise RuntimeError("cota")
    monkeypatch.setattr(code, "build", boom)
    with pytest.raises(RuntimeError):
        code.codigo_criar("Outro", "x", ctx=Context(CFG))
    assert not code.project_dir("Outro").exists()


def test_run_requires_confirmation_and_captures_output_for_the_next_fix(folders, cards):
    registry.load_all()
    assert registry.is_dangerous("codigo_executar", CFG) and registry.is_dangerous("codigo_desfazer", CFG)
    assert not registry.is_dangerous("codigo_criar", CFG)
    folder = code.project_dir("eco")
    (folder / ".viv").mkdir(parents=True)
    (folder / ".viv" / "projeto.json").write_text(json.dumps({"executar": "echo ola-viv"}), encoding="utf-8")
    assert registry.confirm_text("codigo_executar", {"projeto": "eco"}) == "Executar no projeto eco: echo ola-viv"
    result = code.codigo_executar("eco")
    assert "sem erros" in result and "ola-viv" in result
    assert "ola-viv" in (folder / ".viv" / "ultima_execucao.txt").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="não existe projeto"):
        registry.confirm_text("codigo_executar", {"projeto": "fantasma"})


# ---- documentos --------------------------------------------------------------
MARKDOWN = "## Resumo\nTexto com **destaque**.\n\n- um\n- dois\n\n1. passo\n\nItem | Valor\n--- | ---\nA | 1\n"


def test_blocks_parse_headings_lists_and_tables():
    assert docs.blocks(MARKDOWN) == [("h", 2, "Resumo"), ("p", "Texto com **destaque**."), ("ul", ["um", "dois"]),
                                     ("ol", ["passo"]), ("table", [["Item", "Valor"], ["A", "1"]])]


def test_creates_word_pdf_slides_and_sheet_that_can_be_read_back(folders):
    word, preview = docs.create(None, "docx", "Relatório: vendas?", "x", ask=answers(MARKDOWN))
    assert word.parent == folders["documents"] / "Viv" / "Documentos" and word.name == "Relatório vendas.docx"
    assert "destaque" in docs.read_document(word) and "A | 1" in docs.read_document(word) and "Resumo" in preview
    again, _ = docs.create(None, "docx", "Relatório: vendas?", "x", ask=answers(MARKDOWN))
    assert again.name == "Relatório vendas (2).docx"                       # nunca sobrescreve

    pdf, _ = docs.create(None, "pdf", "Guia", "x", ask=answers(MARKDOWN))
    assert pdf.read_bytes().startswith(b"%PDF") and "destaque" in docs.read_document(pdf)

    deck, outline = docs.create(None, "pptx", "Plano", "x", ask=answers(
        {"subtitulo": "2027", "slides": [{"titulo": "Metas", "topicos": ["Crescer", "Simplificar"], "notas": "falar das metas"}]}))
    text = docs.read_document(deck)
    assert "Plano" in text and "Metas" in text and "Crescer" in text and "2. **Metas** (topicos)" in outline

    sheet, table = docs.create(None, "xlsx", "Gastos", "x", ask=answers(
        {"abas": [{"nome": "Mês", "colunas": ["Item", "Valor"], "linhas": [["Luz", 120.5], ["Total", "=SUM(B2:B2)"]]}]}))
    assert "Luz | 120.5" in docs.read_document(sheet) and table.splitlines()[1] == "--- | ---"


def test_documento_criar_opens_file_and_rejects_unknown_type(folders, cards, monkeypatch):
    opened = []
    monkeypatch.setattr(docs, "_open", opened.append)
    monkeypatch.setattr(_llm, "ask", answers(MARKDOWN))
    assert "criado e aberto" in docs.documento_criar("Word", "Ata", "reunião", ctx=Context(CFG))
    assert opened and opened[0].suffix == ".docx"
    with pytest.raises(ValueError, match="word, pdf, slides ou planilha"):
        docs.documento_criar("vídeo", "x", "y", ctx=Context(CFG))
    with pytest.raises(ValueError, match="fs_read"):
        (folders["desktop"] / "a.zip").write_text("x", encoding="utf-8")
        docs.documento_ler("Desktop/a.zip")


# ---- pesquisa profunda -------------------------------------------------------
def test_research_searches_reads_pages_and_cites_numbered_sources():
    prompts = []

    def ask(ctx, prompt, as_json=False):
        prompts.append(prompt)
        return {"buscas": ["a", "b"]} if as_json else "Resposta [1]."
    hits = {"a": [{"title": "Um", "url": "https://x.com/1", "body": "trecho um"}],
            "b": [{"title": "Um", "url": "https://x.com/1", "body": "repetido"}, {"title": "Dois", "url": "https://y.com/2", "body": "trecho dois"},
                  {"title": "Ruim", "url": "javascript:alert(1)", "body": ""}]}
    pages = {"https://x.com/1": "<html><script>ignore()</script><p>Texto &amp; conteúdo</p></html>"}

    def fetch(url):
        return pages[url]                       # y.com falha: cai para o trecho da busca
    report, sources = research.research(None, "tema", ask=ask, search=lambda q, n: hits[q], fetch=fetch)
    assert report == "Resposta [1]." and [s["url"] for s in sources] == ["https://x.com/1", "https://y.com/2"]
    assert "[1] Um" in prompts[1] and "Texto & conteúdo" in prompts[1] and "ignore()" not in prompts[1] and "trecho dois" in prompts[1]


def test_research_without_results_explains():
    with pytest.raises(RuntimeError, match="não trouxe resultados"):
        research.research(None, "tema", ask=lambda *a, **k: {"buscas": ["a"]}, search=lambda q, n: [])


# ---- habilidades e diagnóstico -------------------------------------------------
def test_skills_are_saved_listed_injected_in_the_persona_and_removed(tmp_path, cards):
    cfg = {**CFG, "skills": {"path": str(tmp_path / "h.json")}, "assistant": {}}
    ctx = Context(cfg)
    assert "guardada" in extras.habilidade_salvar("Modo Trabalho", "abrir o Chrome; volume em 30", ctx=ctx)
    extras.habilidade_salvar("modo trabalho", "abrir o Chrome; volume em 20", ctx=ctx)       # mesmo nome substitui
    assert list(skills.load(cfg)) == ["modo trabalho"]
    from datetime import datetime
    assert "- modo trabalho: abrir o Chrome; volume em 20" in system_instruction(cfg, None, datetime(2026, 11, 13, 9, 0))
    assert "volume em 20" in extras.habilidade_listar(ctx=ctx)
    assert "removida" in extras.habilidade_remover("MODO  TRABALHO", ctx=ctx) and skills.prompt_block(cfg) == ""
    with pytest.raises(ValueError):
        skills.save(cfg, "x", "p" * 2000)


def test_diagnostico_shows_table_and_names_what_needs_attention(tmp_path, cards):
    ctx = Context({**CFG, "speaker_id": {"voiceprint_path": str(tmp_path / "nao-existe.json")}})
    text = extras.viv_diagnostico(ctx=ctx)
    table = cards[-1][2]
    assert "Conexão com o Gemini" in text and "Cadastro de voz" in text
    assert table["format"] == "tabela" and table["ok"] is False and "Word | ✓ ok" in table["body"]


class FakeModels:
    def __init__(self, behavior):
        self.behavior, self.asked = behavior, []

    def generate_content(self, model, contents, **extra):
        self.asked.append(model)
        outcome = self.behavior.get(model, "404 NOT_FOUND model is no longer available")
        if isinstance(outcome, str):
            raise RuntimeError(outcome)
        return outcome


def client_with(behavior):
    return type("C", (), {"models": FakeModels(behavior)})()


def test_overloaded_main_model_falls_back_past_retired_models():
    ok = type("R", (), {"text": " pronto "})()
    client = client_with({"principal": "503 UNAVAILABLE high demand", "gemini-3-flash-preview": ok})
    assert _llm.generate(client, "principal", "oi", sleep=lambda s: None) == "pronto"
    assert "gemini-2.5-flash" not in client.models.asked, "modelo desligado não é mais tentado"


def test_error_reports_the_overload_not_the_last_retired_model():
    client = client_with({"principal": "503 UNAVAILABLE high demand"})
    with pytest.raises(RuntimeError, match="sobrecarregado") as error:
        _llm.generate(client, "principal", "oi", sleep=lambda s: None)
    assert "503" in str(error.value) and "404" not in str(error.value)
    with pytest.raises(RuntimeError, match="nenhum modelo"):
        _llm.generate(client_with({}), "principal", "oi", sleep=lambda s: None)
