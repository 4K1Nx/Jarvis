# Criação de material — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Viv combina o material antes de criar, cita fontes em tudo e entrega slides ricos em PowerPoint e/ou apresentação animada, corrigíveis depois.

**Architecture:** Um roteiro estruturado (JSON validado) alimenta dois desenhadores (`deck.write_pptx`, `deck.write_html`). As fontes vêm de `sources.gather` (web e arquivos) e a lista final é escrita pelo programa. Cada material deixa um registro em `data/materiais/` que `documento_ajustar` usa para redesenhar.

**Tech Stack:** Python 3, python-pptx (gráficos e tabelas nativos), httpx, HTML/CSS/JS embutidos sem dependências, pytest.

**Spec:** `docs/superpowers/specs/2026-11-16-criacao-de-material-design.md`

## Global Constraints

- Sem rede e sem modelo nos testes: `ask`, `search`, `fetch` injetados.
- Fontes: web até 6 × 3500 caracteres; arquivos até 5 × 8000 caracteres. Imagem: até 1600 px, 5 MB, 15 s.
- Tamanho: curto 5–7 slides, médio 8–12, longo 13–18. Registros: os 30 mais recentes.
- Todo texto vindo do modelo ou de fontes entra escapado no HTML e por `textContent` na HUD.
- Assinaturas antigas continuam funcionando: `docs.create(ctx, kind, title, request, ask=)` e `documento_criar(tipo, titulo, pedido)`.
- Sem commits (AGENTS.md). Testes: `.venv\Scripts\python.exe -m pytest`.

## Review Focus

- Modelo devolve roteiro com tipo desconhecido ou gráfico com texto no lugar de número: vira `topicos`, a criação não cai.
- Modelo cita `[9]` com só 3 fontes: a citação não vira fonte na lista.
- Fonte ou roteiro contendo `<script>`: sai escapado no HTML.
- Busca de imagem falha ou devolve HTML/arquivo enorme: slide sai sem imagem.
- Clique numa opção de pergunta já fechada ou inexistente: recusado, nada chega ao modelo.

---

### Task 1: `perguntar` (ferramenta, rota e cartão)

**Files:** Modify `viv/tools/hud.py`, `server.py`, `web/cards.js`, `web/app.js`, `web/viv.css`, `tests/test_tools.py` (lista de nomes), Create `tests/test_perguntar.py`

**Produces:**
- `hud.perguntar(pergunta: str, opcoes: list[str], sugestao: str = "", ctx=None) -> str`: 2 a 5 opções (senão `ValueError`); guarda em `hud.OPEN: dict[str, list[str]]`; emite `BUS.emit("ask", pergunta, options=[...], suggestion=...)`.
- `hud.answer(pergunta: str, opcao: str) -> bool`: remove e devolve True só se a opção pertence à pergunta aberta.
- `hud.close_questions() -> None`: limpa `OPEN` e emite `ask_done`.
- `POST /api/answer` com JSON `{pergunta, opcao}`: `same_origin`; 400 se `answer` der False; senão `viv.notify("O usuário escolheu na tela: “{opcao}” para “{pergunta}”.")`.
- HUD: `VivCards.ask(event)` empilha linhas num cartão no mesmo lugar das confirmações (`confirmSlot` é das confirmações; criar um `askSlot` irmão); sugestão com classe `suggested`; clique faz o POST e remove a linha; `VivCards.askDone()`; cartão some após 120 s.

- [ ] Testes: `perguntar` com 1 opção levanta; emite evento com opções e sugestão; `answer` True uma vez só e False para opção de fora; `close_questions` esvazia. Rota: opção inválida → 400 e nenhum `notify`; válida → 200 e um `notify` contendo a opção.
- [ ] Implementar; `pytest` verde; `node --check` nos `.js`.

### Task 2: `viv/tools/sources.py`

**Files:** Create `viv/tools/sources.py`, `tests/test_fontes.py`; Modify `viv/tools/research.py` (usa `sources.web`)

**Produces:**
```python
def web(ctx, topic: str, ask=None, search=None, fetch=None) -> list[dict]      # {n,titulo,origem,texto}; move o planejamento, a busca e a leitura de research.research
def files(paths: list[str]) -> list[dict]                                       # FileNotFoundError/ValueError com o nome do arquivo
def gather(ctx, topic: str, mode: str, paths: list[str], ask=None, search=None, fetch=None) -> list[dict]   # mode: web|arquivos|ambos|nenhuma; renumera de 1
def listing(sources: list[dict]) -> str                                         # bloco "[n] título (origem)\ntexto" para o pedido ao modelo
def cited(text: str, sources: list[dict]) -> list[dict]                         # só as fontes cujo [n] aparece em text, em ordem
RULES_WITH: str; RULES_WITHOUT: str; NO_SOURCES_NOTE: str                       # textos do spec, seção 3
```
`page_text` e os limites ficam em `sources.py`; `research.py` os importa de lá. Imagens entre os `paths` (png, jpg, jpeg, webp) são ignoradas por `files` (são da Task 3).

- [ ] Testes: os quatro modos; arquivo inexistente levanta antes de qualquer `ask`; 7 arquivos → 5 lidos; texto cortado em 8000; `cited("a [1] b [9]", 3 fontes)` devolve só a 1; `research.research` continua passando em `tests/test_criacao.py`.
- [ ] Implementar; `pytest` verde.

### Task 3: `viv/tools/images.py`

**Files:** Create `viv/tools/images.py`, `tests/test_imagens.py`

**Produces:**
```python
LICENSES = "cc0,pdm,by,by-sa"
def find(query: str, folder: Path, fetch_json=None, fetch_bytes=None) -> dict | None   # {path,titulo,autor,licenca,origem}
def local(name: str, paths: list[str]) -> dict | None                                  # arquivo de imagem do usuário cujo nome contém `name`
def credit(image: dict) -> str                                                          # "Imagem: título, autor, licença, origem"
```
`find` consulta `https://api.openverse.org/v1/images/?q=…&page_size=5&license=…&aspect_ratio=wide`, tenta os resultados em ordem, valida com Pillow (é imagem, ≤ 5 MB), reduz para ≤ 1600 px de largura e grava JPEG em `folder`. Qualquer exceção devolve `None`.

- [ ] Testes: resultado bom grava arquivo e devolve metadados; bytes que não são imagem → próximo resultado; todos ruins → None; `fetch_json` levantando → None; `credit` contém autor e licença.
- [ ] Implementar; `pytest` verde.

### Task 4: `viv/tools/deck.py` (roteiro e dois desenhadores)

**Files:** Create `viv/tools/deck.py`, `tests/test_deck.py`; Modify `viv/tools/docs.py` (remove `write_pptx`, importa de `deck`)

**Produces:**
```python
TYPES = ("capa","secao","topicos","duas_colunas","destaque","citacao","tabela","grafico","imagem","encerramento")
THEMES = {"claro": {...}, "escuro": {...}, "colorido": {...}}     # chaves: back, ink, dim, accent, accent2 (hex)
SIZES = {"curto": (5, 7), "medio": (8, 12), "longo": (13, 18)}
def prompt(title: str, request: str, size: str, sources_block: str, images: bool) -> str
def normalize(data, title: str) -> dict        # {"slides": [...]} só com tipos válidos; inválido vira "topicos"; garante capa no início
def write_pptx(title: str, deck: dict, sources: list[dict], theme: str, path: Path) -> None
def write_html(title: str, deck: dict, sources: list[dict], theme: str, path: Path) -> None
def outline(deck: dict) -> str                 # prévia em markdown para a tela
```
`normalize`: `grafico` exige `grafico` em barras|linhas|pizza, `categorias` não vazia e toda série com valores numéricos do mesmo tamanho; `tabela` corta em 6 colunas × 8 linhas; `topicos` em 5. Cada slide pode levar `_imagem` (dict de `images`) posto por quem chama. `write_pptx`: gráficos com `chart_data`/`add_chart`, tabela com `add_table`, último slide "Fontes" se houver fontes. `write_html`: arquivo único; imagens em base64; gráficos em SVG; navegação por setas, espaço, clique e `F`; `prefers-reduced-motion`.

- [ ] Testes: `normalize` para cada defeito do Review Focus; `write_pptx` com um roteiro de todos os tipos abre com python-pptx, tem `len(slides)+1` slides com fontes, `has_chart` e `has_table` verdadeiros em algum shape, notas presentes; `write_html` não contém `http://`/`https://` fora da lista de fontes como `src`/`href` de recurso (`<script src`, `<link`, `<img src="http`), tem um `<section` por slide e escapa `<script>alert(1)</script>` vindo do título de um slide.
- [ ] Implementar; `pytest` verde (incluindo o teste de pptx existente em `tests/test_criacao.py`, ajustado ao novo roteiro se necessário).

### Task 5: `documento_criar` novo, registro e `documento_ajustar`

**Files:** Modify `viv/tools/docs.py`, `viv/persona.py`, `tests/test_criacao.py`, `tests/test_tools.py`; Create `tests/test_material.py`

**Produces:**
```python
def create(ctx, kind, title, request, ask=None, *, sources_mode="nenhuma", files=(), fmt="powerpoint", theme="escuro",
           size="medio", images=False, search=None, fetch=None, find_image=None) -> tuple[Path, str]
def record_for(target: str) -> dict | None            # pelo caminho ou pelo título, o mais recente
def adjust(ctx, target: str, request: str, ask=None) -> tuple[list[Path], str]
```
- `documento_criar(tipo, titulo, pedido, fontes="nenhuma", arquivos=None, formato="powerpoint", tema="escuro", tamanho="medio", imagens="nao", ctx=None)`; na declaração, `fontes` e `tamanho` são obrigatórios; `arquivos` é `{"type":"array","items":{"type":"string"}}`. Chama `hud.close_questions()` ao começar. `formato=ambos` grava `.pptx` e `.html` com o mesmo nome base e abre o `.html`.
- Word/PDF: fontes no pedido; ao final acrescenta `## Fontes` com `sources.cited` (ou `NO_SOURCES_NOTE`). Planilha: aba "Fontes" com todas as fontes de `gather` (não há texto corrido para citar).
- Registro: `data/materiais/<carimbo>-<slug>.json` com `titulo, tipo, pedido, conteudo, fontes, opcoes, arquivos`. `adjust` pede ao modelo o conteúdo completo corrigido (mesmo formato, mesmas regras e fontes), valida e regrava os mesmos caminhos.
- `documento_ajustar(arquivo, pedido)`; sem registro: `ValueError("só consigo ajustar materiais que eu mesma criei …")`.
- Persona: item novo com a regra de combinar antes (spec, seção 2) e o uso de `perguntar` e `documento_ajustar`.

- [ ] Testes: `formato=ambos` gera dois arquivos do mesmo roteiro; docx com fontes termina com seção "Fontes" contendo só as citadas; sem fontes contém a nota; fonte inexistente citada não aparece; `adjust` regrava o mesmo caminho com o conteúdo novo; `adjust` sem registro levanta; limite de 30 registros.
- [ ] Implementar; `pytest` inteiro verde.
- [ ] Prova real: gerar um deck de exemplo com `ask` falso contendo todos os tipos, nos dois formatos, e abrir o `.html` e o `.pptx` para conferir a aparência.
