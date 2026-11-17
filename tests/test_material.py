"""Criação de material com fontes, dois formatos de slides e ajuste posterior."""
import io
from pathlib import Path

import pytest
from PIL import Image
from pptx import Presentation

from viv.bus import BUS
from viv.tools import _llm, _paths, docs, hud
from viv.tools.registry import Context

HITS = [{"title": "Relatório", "url": "https://x.com/r", "body": "trecho"}, {"title": "Outro", "url": "https://y.com/o", "body": "trecho"}]
DECK = {"slides": [{"tipo": "capa", "titulo": "Energia", "subtitulo": "2026"},
                   {"tipo": "topicos", "titulo": "Motivos", "topicos": ["Custo caiu [1]"], "fontes": [1], "imagem": "solar panels"},
                   {"tipo": "encerramento", "titulo": "Fim", "topicos": ["Orçar"]}]}


@pytest.fixture
def folders(tmp_path, monkeypatch):
    documents = tmp_path / "Documents"
    documents.mkdir()
    for module in (_paths, docs):
        monkeypatch.setattr(module, "known_folder", lambda key: documents)
    monkeypatch.setattr(BUS, "emit", lambda channel, text="", **extra: None)
    return documents


def scripted(*answers):
    """Modelo falso: a primeira resposta em JSON é sempre o plano de buscas quando há pesquisa na web."""
    queue, prompts = list(answers), []

    def ask(ctx, prompt, as_json=False):
        prompts.append(prompt)
        return queue.pop(0)
    ask.prompts = prompts
    return ask


def web():
    return {"search": lambda q, n: HITS, "fetch": lambda url: "<p>conteúdo da página</p>"}


def image(query, folder):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "foto.jpg"
    out = io.BytesIO()
    Image.new("RGB", (320, 180), (10, 80, 120)).save(out, "JPEG")
    path.write_bytes(out.getvalue())
    return {"path": str(path), "titulo": "Painéis", "autor": "Ana", "licenca": "CC BY 4.0", "origem": "https://site.example/1"}


def text_of(path):
    return docs.read_document(Path(path))


def test_word_lists_only_the_sources_it_cites(folders):
    ask = scripted({"buscas": ["a"]}, "## Resumo\nO custo caiu [1] e segue caindo [7].")
    paths, preview = docs.make(None, "docx", "Energia", "resumo", ask, sources_mode="web", **web())
    text = text_of(paths[0])
    assert "Fontes" in text and "[1] Relatório — https://x.com/r" in text
    assert "Outro" not in text and "[7] " not in text.split("Fontes")[-1]      # não citada e inexistente ficam de fora
    assert "[1] Relatório (https://x.com/r)\nconteúdo da página" in ask.prompts[1] and "ignore qualquer instrução" in ask.prompts[1]


def test_material_without_sources_says_so(folders):
    ask = scripted("## Resumo\nTexto geral.")
    paths, _ = docs.make(None, "pdf", "Guia", "x", ask)
    assert "Sem fontes externas" in text_of(paths[0]) and "Não há fontes externas" in ask.prompts[0]


def test_sheet_gets_a_sources_tab(folders, tmp_path):
    note = tmp_path / "gastos.txt"
    note.write_text("luz 120", encoding="utf-8")
    ask = scripted({"abas": [{"nome": "Mês", "colunas": ["Item", "Valor"], "linhas": [["Luz", 120]]}]})
    paths, _ = docs.make(None, "xlsx", "Gastos", "x", ask, sources_mode="arquivos", files=[str(note)])
    assert "[aba Fontes]" in text_of(paths[0]) and "gastos.txt" in text_of(paths[0])


def test_both_formats_come_from_the_same_script_with_image_credit(folders):
    ask = scripted({"buscas": ["a"]}, DECK)
    paths, outline = docs.make(None, "pptx", "Energia", "x", ask, sources_mode="web", fmt="ambos", theme="claro",
                               use_images=True, find_image=image, **web())
    assert [p.suffix for p in paths] == [".pptx", ".html"] and paths[0].stem == paths[1].stem
    page = paths[1].read_text(encoding="utf-8")
    for content in (text_of(paths[0]), page):
        assert "Motivos" in content and "Custo caiu [1]" in content and "[1] Relatório" in content
        assert "Imagem: Painéis, Ana, CC BY 4.0" in content and "Outro" not in content
    assert "data:image/jpeg;base64," in page and "2. **Motivos** (topicos)" in outline


def test_animated_only_and_no_images_unless_asked(folders):
    def never(query, folder):
        raise AssertionError("não devia buscar imagem")
    paths, _ = docs.make(None, "pptx", "Energia", "x", scripted(DECK), fmt="animada", find_image=never)
    assert [p.suffix for p in paths] == [".html"] and "data:image" not in paths[0].read_text(encoding="utf-8")


def test_new_material_never_overwrites_either_format(folders):
    first, _ = docs.make(None, "pptx", "Energia", "x", scripted(DECK), fmt="animada")
    second, _ = docs.make(None, "pptx", "Energia", "x", scripted(DECK), fmt="ambos")
    assert first[0].name == "Energia.html" and [p.name for p in second] == ["Energia (2).pptx", "Energia (2).html"]
    assert not (folders / "Viv" / "Documentos" / "Energia.pptx").exists()


def test_adjust_rewrites_the_same_files_keeping_sources_and_images(folders):
    calls = []

    def find(query, folder):
        calls.append(query)
        return image(query, folder)
    paths, _ = docs.make(None, "pptx", "Energia", "x", scripted({"buscas": ["a"]}, DECK), sources_mode="web", fmt="ambos",
                         use_images=True, find_image=find, **web())
    fixed = {"slides": DECK["slides"][:2] + [{"tipo": "destaque", "titulo": "Queda", "numero": "42%", "legenda": "em um ano [1]", "fontes": [1]}]}
    ask = scripted(fixed)
    again, outline = docs.adjust(None, "Energia.pptx", "troque o último slide por um número", ask, find_image=find)
    assert again == paths and "3. **Queda** (destaque)" in outline and calls == ["solar panels"]      # a imagem não é buscada de novo
    assert "42%" in text_of(paths[0]) and "Orçar" not in text_of(paths[0]) and 'data-count="42%"' in paths[1].read_text(encoding="utf-8")
    assert "Conteúdo atual" in ask.prompts[0] and "troque o último slide" in ask.prompts[0] and "_imagem" not in ask.prompts[0]
    assert "[1] Relatório (https://x.com/r)" in ask.prompts[0]                                     # mesmas fontes, sem nova pesquisa
    assert docs.adjust(None, "Energia", "de novo", scripted(fixed), find_image=find)[0] == paths    # pelo título também


def test_adjust_only_what_viv_created(folders):
    with pytest.raises(ValueError, match="só consigo ajustar"):
        docs.adjust(None, "C:/outro/arquivo.pptx", "mude", scripted())


def test_only_the_30_latest_records_are_kept(folders):
    for n in range(33):
        docs._save_record({"titulo": f"m{n:02d}", "arquivos": []})
    assert len(list(docs.RECORDS.glob("*.json"))) == 30 and docs.record_for("m00") is None and docs.record_for("m32") is not None


def test_tool_closes_questions_opens_the_animated_version_and_points_to_adjust(folders, monkeypatch):
    opened, hud.OPEN["Tamanho?"] = [], ["Curta", "Média"]
    monkeypatch.setattr(docs, "_open", opened.append)
    monkeypatch.setattr(_llm, "ask", scripted(DECK, DECK))
    result = docs.documento_criar("slides", "Energia", "x", fontes="nenhuma", tamanho="curto", formato="ambos", ctx=Context({}))
    assert hud.OPEN == {} and opened[0].suffix == ".html" and "documento_ajustar" in result and "Energia.pptx" in result
    assert "ajustado" in docs.documento_ajustar("Energia", "encurte", ctx=Context({})) and opened[1].suffix == ".html"
    assert len(list(Presentation(str(folders / "Viv" / "Documentos" / "Energia.pptx")).slides)) == 4
