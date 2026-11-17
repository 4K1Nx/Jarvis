import io
import re

import pytest
from PIL import Image
from pptx import Presentation

from viv.tools import deck

SOURCES = [{"n": 1, "titulo": "Relatório anual", "origem": "https://x.com/r", "texto": "t"},
           {"n": 2, "titulo": "notas.txt", "origem": "C:/notas.txt", "texto": "t"},
           {"credito": "Imagem: Usina, Ana, CC BY 4.0, https://site.example/1"}]
FULL = {"slides": [
    {"tipo": "capa", "titulo": "Energia solar", "subtitulo": "Panorama 2026", "notas": "abrir"},
    {"tipo": "secao", "titulo": "Contexto", "subtitulo": "De onde partimos"},
    {"tipo": "topicos", "titulo": "Por que agora", "topicos": ["Custo caiu", "Incentivos", "Demanda"], "fontes": [1], "notas": "explicar"},
    {"tipo": "duas_colunas", "titulo": "Telhado ou usina", "esquerda": {"titulo": "Telhado", "topicos": ["Perto do consumo"]},
     "direita": {"titulo": "Usina", "topicos": ["Escala"]}},
    {"tipo": "destaque", "titulo": "Crescimento", "numero": "42%", "legenda": "de aumento em um ano", "fontes": [1]},
    {"tipo": "citacao", "texto": "O sol não manda conta.", "autor": "Ditado"},
    {"tipo": "tabela", "titulo": "Custos", "colunas": ["Item", "Valor"], "linhas": [["Painel", "R$ 900"], ["Inversor", "R$ 3.000"]]},
    {"tipo": "grafico", "titulo": "Capacidade", "grafico": "barras", "categorias": ["2024", "2025"],
     "series": [{"nome": "GW", "valores": [37, 52.5]}], "fontes": [1, 9]},
    {"tipo": "grafico", "titulo": "Matriz", "grafico": "pizza", "categorias": ["Solar", "Outras"], "series": [{"nome": "%", "valores": [20, 80]}]},
    {"tipo": "grafico", "titulo": "Preço", "grafico": "linhas", "categorias": ["a", "b", "c"], "series": [{"nome": "R$", "valores": [3, 2, 1]}]},
    {"tipo": "imagem", "titulo": "Uma usina", "imagem": "solar farm", "legenda": "no interior"},
    {"tipo": "encerramento", "titulo": "Próximos passos", "topicos": ["Orçar", "Instalar"]},
]}


def test_normalize_keeps_every_valid_type_and_cleans_source_numbers():
    slides = deck.normalize(FULL, "Energia solar")["slides"]
    assert [s["tipo"] for s in slides] == [s["tipo"] for s in FULL["slides"]]
    assert slides[7]["fontes"] == [1, 9] and slides[7]["series"][0]["valores"] == [37.0, 52.5]


@pytest.mark.parametrize("broken", [
    {"tipo": "holograma", "titulo": "X", "topicos": ["a"]},
    {"tipo": "grafico", "titulo": "X", "grafico": "barras", "categorias": ["a", "b"], "series": [{"nome": "s", "valores": ["muito", 2]}]},
    {"tipo": "grafico", "titulo": "X", "grafico": "barras", "categorias": ["a", "b"], "series": [{"nome": "s", "valores": [1]}]},
    {"tipo": "grafico", "titulo": "X", "grafico": "radar", "categorias": ["a"], "series": [{"nome": "s", "valores": [1]}]},
    {"tipo": "tabela", "titulo": "X", "colunas": [], "linhas": []},
    {"tipo": "duas_colunas", "titulo": "X", "esquerda": {"titulo": "só um lado", "topicos": ["a"]}},
    {"tipo": "destaque", "titulo": "X", "legenda": "sem número"},
    {"tipo": "imagem", "titulo": "X", "legenda": "sem consulta"},
    {"titulo": "X", "topicos": ["roteiro antigo, sem tipo"]},
])
def test_what_cannot_be_drawn_becomes_topics(broken):
    slides = deck.normalize({"slides": [broken]}, "Título")["slides"]
    assert [s["tipo"] for s in slides] == ["capa", "topicos"] and slides[0]["titulo"] == "Título"


def test_normalize_limits_and_edge_cases():
    table = {"tipo": "tabela", "titulo": "T", "colunas": list("abcdefgh"), "linhas": [list("12345678")] * 12}
    pie = {"tipo": "grafico", "titulo": "P", "grafico": "pizza", "categorias": ["a", "b"], "series": [{"nome": "", "valores": [0, 0]}]}
    comma = {"tipo": "grafico", "titulo": "C", "grafico": "barras", "categorias": ["a"], "series": [{"nome": "", "valores": ["1.234,5"]}]}
    slides = deck.normalize({"slides": [table, pie, comma]}, "T")["slides"]
    assert len(slides[1]["colunas"]) == 6 and len(slides[1]["linhas"]) == 8 and len(slides[1]["linhas"][0]) == 6
    assert slides[2]["grafico"] == "barras"                       # pizza sem total vira barras
    assert slides[3]["series"][0]["valores"] == [1234.5]
    with pytest.raises(RuntimeError, match="não devolveu os slides"):
        deck.normalize({"slides": []}, "T")
    with pytest.raises(RuntimeError):
        deck.normalize("texto solto", "T")


def photo(tmp_path):
    path = tmp_path / "foto.jpg"
    out = io.BytesIO()
    Image.new("RGB", (640, 360), (30, 120, 90)).save(out, "JPEG")
    path.write_bytes(out.getvalue())
    return {"path": str(path), "titulo": "Usina", "autor": "Ana", "licenca": "CC BY 4.0", "origem": "https://site.example/1"}


def ready(tmp_path):
    data = deck.normalize(FULL, "Energia solar")
    data["slides"][2]["_imagem"] = data["slides"][10]["_imagem"] = photo(tmp_path)
    return data


def test_pptx_has_native_chart_table_notes_pictures_and_a_sources_slide(tmp_path):
    path = tmp_path / "a.pptx"
    deck.write_pptx("Energia solar", ready(tmp_path), SOURCES, "claro", path)
    slides = list(Presentation(str(path)).slides)
    assert len(slides) == len(FULL["slides"]) + 1
    shapes = [shape for slide in slides for shape in slide.shapes]
    assert sum(shape.has_chart for shape in shapes) == 3 and sum(shape.has_table for shape in shapes) == 1
    assert sum(shape.shape_type == 13 for shape in shapes) == 2                     # as duas imagens
    assert slides[2].notes_slide.notes_text_frame.text == "explicar"
    text = lambda slide: " ".join(s.text_frame.text for s in slide.shapes if s.has_text_frame)      # noqa: E731
    assert "Fontes: [1]" in text(slides[7]) and "[9]" not in text(slides[7])         # fonte que não existe não aparece
    last = text(slides[-1])
    assert "[1] Relatório anual — https://x.com/r" in last and "Imagem: Usina, Ana" in last


def test_pptx_without_sources_ends_with_the_note(tmp_path):
    path = tmp_path / "b.pptx"
    deck.write_pptx("T", deck.normalize(FULL, "T"), [], "tema-que-nao-existe", path, note="Sem fontes externas.")
    last = list(Presentation(str(path)).slides)[-1]
    assert "Sem fontes externas." in " ".join(s.text_frame.text for s in last.shapes if s.has_text_frame)


def test_html_is_one_self_contained_file_with_every_slide(tmp_path):
    path = tmp_path / "a.html"
    deck.write_html("Energia solar", ready(tmp_path), SOURCES, "escuro", path)
    page = path.read_text(encoding="utf-8")
    assert page.count('<section class="slide') == len(FULL["slides"]) + 1
    assert not re.search(r'<(script|link|img|iframe)[^>]+(src|href)=', page) and "@import" not in page and "url(http" not in page
    assert page.count("data:image/jpeg;base64,") == 2 and "<svg" in page and 'class="bar"' in page and 'class="slice"' in page
    assert 'data-count="42%"' in page and "[1] Relatório anual" in page and "Fontes: [1]<" in page


def test_html_escapes_everything_that_comes_from_the_script(tmp_path):
    evil = "<script>alert(1)</script>"
    data = deck.normalize({"slides": [{"tipo": "topicos", "titulo": evil, "topicos": [evil]},
                                      {"tipo": "tabela", "titulo": "t", "colunas": [evil], "linhas": [[evil]]},
                                      {"tipo": "grafico", "titulo": "g", "grafico": "barras", "categorias": [evil],
                                       "series": [{"nome": evil, "valores": [1]}]}]}, evil)
    path = tmp_path / "x.html"
    deck.write_html(evil, data, [{"n": 1, "titulo": evil, "origem": evil, "texto": ""}], "claro", path)
    page = path.read_text(encoding="utf-8")
    assert "<script>alert(1)" not in page and page.count("<script>") == 1 and "&lt;script&gt;" in page


def test_prompt_changes_with_sources_size_and_images():
    with_all = deck.prompt("T", "pedido", "curto", "REGRAS", True, True)
    assert "De 5 a 7 slides" in with_all and "REGRAS" in with_all and "EM INGLÊS" in with_all and "só com números que estejam nas fontes" in with_all
    bare = deck.prompt("T", "pedido", "longo", "REGRAS", False, False)
    assert "De 13 a 18 slides" in bare and "EM INGLÊS" not in bare and "não use os tipos" in bare
