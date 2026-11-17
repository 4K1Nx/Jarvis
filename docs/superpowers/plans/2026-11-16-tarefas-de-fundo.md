# Tarefas de fundo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nenhuma ferramenta da Viv congela a conversa por mais de 4 s: o que demora vira tarefa de fundo, com progresso consultável e aviso no fim.

**Architecture:** `viv/tasks.py` executa a chamada já autorizada numa thread e espera um limite; estourado o limite, registra a tarefa e devolve ao modelo um texto "em segundo plano". O portão (`viv/safety.py`) passa a executar por ele. O fim da tarefa chega ao modelo por `Viv.announce`, uma fila entregue só com ela calada e ouvindo.

**Tech Stack:** Python 3 (threading, contextvars), pytest com asyncio_mode=auto, HUD em JavaScript puro.

**Spec:** `docs/superpowers/specs/2026-11-16-tarefas-de-fundo-design.md`

## Global Constraints

- Limite padrão: `tasks.background_after_seconds: 4` no `config.yaml`.
- Ação perigosa nunca executa antes da confirmação; só a execução autorizada vai para o fundo.
- Resultado no aviso de fim: até 2000 caracteres. Histórico: 20 tarefas terminadas.
- Sem commits: o `AGENTS.md` exige autorização do usuário. Cada tarefa termina com a suíte verde.
- Não ler nem expor `.env`. Textos e comentários em português, no estilo dos arquivos existentes.
- Rodar testes com `.venv\Scripts\python.exe -m pytest`.

## Review Focus

- Conexão do Gemini cai com tarefa rodando: o aviso de fim não pode se perder (fica na fila até a próxima sessão).
- O modelo repete a mesma chamada enquanto roda: não executa de novo.
- Ferramenta levanta exceção depois de ir para o fundo: tarefa "falhou" e o usuário é avisado.
- Duas chamadas ao mesmo módulo (navegador): a segunda só começa quando a primeira termina.
- Tarefa termina com a Viv falando: o aviso espera o áudio acabar.

---

### Task 1: `viv/tasks.py` e progresso por tarefa

**Files:**
- Create: `viv/tasks.py`, `tests/test_tasks.py`
- Modify: `viv/tools/registry.py` (`progress`, `call`, `Context.tasks`)

**Interfaces — Produces:**

```python
class Tasks:
    def __init__(self, after: float = 4.0, on_done: Callable[[dict], None] | None = None,
                 clock: Callable[[], float] = time.monotonic): ...
    def run(self, name: str, args: dict | None, call: Callable[[], str], title: str = "", group: str = "") -> str
    def snapshot(self) -> list[dict]   # {id, title, status: rodando|pronta|falhou, step, value, seconds, result}
def note(label: str, value: float | None) -> bool   # módulo: atualiza a tarefa da thread atual; True se ela está no fundo
def backgrounded() -> bool                          # a thread atual é de uma tarefa que já foi para o fundo?
```

`run` devolve o resultado de `call()` se terminar em `after` segundos; senão um texto que começa com
`"em segundo plano: tarefa {id} ({title})"`. Mesma `(name, args)` rodando devolve texto que começa com
`"já está rodando"`. `group` igual serializa (uma `threading.Lock` por grupo, tomada dentro da thread).
Resultado que começa com `"erro"` ou exceção de `call` marcam `falhou`. `on_done(task_dict)` só é chamado
para tarefas que foram para o fundo. Emite `BUS.emit("tasks", items=[...rodando no fundo...])` ao ir para
o fundo, a cada `note` e ao terminar; ao ir para o fundo emite também `BUS.emit("progress", "", value=None, done=True)`.

- [ ] **Step 1: testes que falham** em `tests/test_tasks.py` (ferramenta falsa controlada por `threading.Event`, `after=0.05`; `on_done` coleta numa lista e sinaliza um Event):
  - `test_fast_call_returns_result`: `run("t", {}, lambda: "ok") == "ok"`; `on_done` não chamado; `snapshot() == []`.
  - `test_slow_call_goes_to_background`: resultado começa com `"em segundo plano: tarefa 1 (Título)"`; `snapshot()[0]["status"] == "rodando"`; solta o Event; `on_done` recebe `status == "pronta"` e `result == "feito"`.
  - `test_duplicate_while_running`: segunda `run` com mesmos nome e args começa com `"já está rodando"` e a função roda uma vez só.
  - `test_same_group_runs_one_at_a_time`: duas tarefas com `group="browser"`; a segunda só registra início depois de a primeira soltar.
  - `test_note_goes_to_the_right_task`: `note("Etapa 2", 0.5)` chamado de dentro da tarefa aparece em `snapshot()[0]["step"] == "Etapa 2"` e `value == 0.5`; fora de tarefa devolve `False`.
  - `test_failure_in_background_is_reported`: função que levanta `RuntimeError("quebrou")` depois de ir para o fundo: `on_done` recebe `status == "falhou"` e `"quebrou" in result`.
  - `test_long_result_is_cut`: resultado de 5000 caracteres chega a `on_done` com `len(result) <= 2000`.
  - `test_history_keeps_20`: 25 tarefas de fundo terminadas deixam `len(snapshot()) == 20`.
- [ ] **Step 2:** rodar `pytest tests/test_tasks.py` — falha por módulo inexistente.
- [ ] **Step 3:** implementar `viv/tasks.py` (contextvar para a tarefa atual; não importa `registry`).
- [ ] **Step 4:** em `registry.py`: `Context.tasks: Any = None`; `progress()` chama `tasks.note(label, value)` e só emite o evento `progress` quando devolver `False`; o `finally` de `call` só emite `done=True` quando `not tasks.backgrounded()`.
- [ ] **Step 5:** `pytest` inteiro verde.

### Task 2: o portão executa pelas tarefas

**Files:** Modify `viv/safety.py`, `tests/test_safety.py`

**Interfaces — Consumes:** `Tasks.run`. **Produces:** `Gate.tasks` (atributo, `None` por padrão) e `Gate._call(name, args) -> str`.

`_call` usa `self.tasks.run(name, args, lambda: registry.call(name, args, self.ctx), title=registry.describe(name, args), group=registry.module_of(name))`, ou `registry.call` direto sem `tasks`. As três execuções do portão (comum, voz, confirmada) passam por `_call`.

- [ ] **Step 1: testes que falham** em `tests/test_safety.py`, com um `FakeTasks` que grava as chamadas e devolve `call()`:
  - `test_common_tool_runs_through_tasks`: `gate.tasks = fake`; `submit("t_comum", {"x": "a"}) == "feito a"`; `fake.calls == [("t_comum", {"x": "a"})]`.
  - `test_dangerous_tool_reaches_tasks_only_after_confirmation`: após `submit("t_perigosa", ...)` `fake.calls == []`; após `gate.on_click(True)` tem uma chamada.
- [ ] **Step 2:** rodar e ver falhar. **Step 3:** implementar. **Step 4:** `pytest` inteiro verde.

### Task 3: aviso no momento certo, ferramenta e persona

**Files:** Modify `viv/live.py`, `main.py`, `config.yaml`, `viv/tools/assistant.py`, `viv/persona.py`, `tests/test_live.py`, `tests/test_tools.py`

**Interfaces — Produces:** `Viv.announce(text: str) -> None` (thread-safe; acorda a Viv). Ferramenta `tarefas_andamento` (sem parâmetros, `card=False`).

- `announce` guarda numa fila própria e pede para acordar. O `_watchdog` entrega (como `[Aviso do sistema] …`) só quando `not playing and self.state == State.LISTENING`. A fila não é limpa em falha de conexão nem ao dormir.
- `main.py`: `tasks = Tasks(after=cfg["tasks"]["background_after_seconds"] ou 4, on_done=...)`; `ctx.tasks = gate.tasks = tasks`. `on_done` chama `viv.announce` com: `A tarefa em segundo plano “{title}” {terminou|falhou}. Resultado: {result}. Termine o que estava dizendo e conte ao usuário em uma ou duas frases.`
- `tarefas_andamento`: uma linha por tarefa de `ctx.tasks.snapshot()` (`título — etapa, 40%, há 35 s` / `título — pronta: resultado[:200]`), ou `"nenhuma tarefa em segundo plano"`.
- Persona, um item novo na lista: tarefas demoradas seguem em segundo plano; dizer em uma frase que está cuidando e continuar a conversa; `tarefas_andamento` para o andamento; não chamar de novo; contar o resultado quando chegar o aviso.

- [ ] **Step 1: testes que falham**
  - `test_live.py::test_announce_waits_for_playback`: acordada, `env.audio` tocando, `viv.announce("pronto")`: nada com "pronto" enviado à sessão; ao parar de tocar e voltar a LISTENING, a sessão recebe texto contendo "pronto".
  - `test_live.py::test_announce_wakes_sleeping_viv`: dormindo, `announce("pronto")` leva a uma conexão e ao envio.
  - `test_tools.py::test_tarefas_andamento_lists_running`: `Context` com `tasks` falso cujo `snapshot` devolve uma tarefa rodando com `step="Etapa 2"`, `value=0.4`; o resultado contém o título, "Etapa 2" e "40%". Sem tarefas: "nenhuma tarefa em segundo plano".
- [ ] **Step 2:** ver falhar. **Step 3:** implementar. **Step 4:** `pytest` inteiro verde.

### Task 4: lista de tarefas na HUD

**Files:** Modify `web/index.html`, `web/app.js`, `web/viv.css`

- `<div id="tasks" role="status" aria-live="polite" hidden>` acima de `#progress`. Evento `tasks` reconstrói a lista: uma linha por item com título, etapa e a mesma trilha `.progress-track` (classe `unknown` sem `value`). Texto só por `textContent`. Lista vazia esconde. Respeitar `prefers-reduced-motion` como `#progress`.
- [ ] **Step 1:** implementar. **Step 2:** abrir a HUD, disparar pelo console `window.dispatchEvent`/WebSocket de teste ou uma ferramenta lenta real e conferir que a linha aparece e some; `pytest` inteiro verde (há testes do servidor que servem os arquivos estáticos).
