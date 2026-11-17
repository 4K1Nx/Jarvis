"""Tarefas de fundo: nenhuma ferramenta congela a conversa.

Toda chamada já autorizada pelo portão roda numa thread. Se terminar dentro do limite, o resultado
volta na hora, como sempre. Se passar, a chamada vira uma tarefa: o modelo recebe "em segundo plano"
e segue a conversa, o progresso fica consultável (snapshot) e o fim é avisado por `on_done`.

Uma thread Python não pode ser interrompida com segurança: não há cancelamento aqui. As paradas que
existem são as das próprias ferramentas (codigo_parar, agente_parar, tela_parar_vigia).
"""
import contextvars
import json
import threading
import time
from typing import Callable

from viv.bus import BUS

RESULT_LIMIT = 2000        # caracteres do resultado levados ao aviso de fim
HISTORY = 20               # tarefas terminadas que continuam na lista
_current: contextvars.ContextVar = contextvars.ContextVar("viv_tarefa", default=None)


def note(label: str, value: float | None) -> bool:
    """Etapa atual da tarefa desta thread. Devolve True se ela já está em segundo plano (a barra de
    progresso da conversa não é mais dela)."""
    task = _current.get()
    if task is None:
        return False
    task["step"], task["value"] = str(label)[:120], value
    if not task["background"]:
        return False
    task["owner"]._publish()
    return True


def backgrounded() -> bool:
    task = _current.get()
    return bool(task and task["background"])


class Tasks:
    def __init__(self, after: float = 4.0, on_done: Callable[[dict], None] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.after, self.on_done, self.clock = float(after), on_done, clock
        self._lock = threading.Lock()
        self._groups: dict[str, threading.Lock] = {}
        self._tasks: list[dict] = []          # as que foram para o fundo, rodando ou terminadas
        self._running: dict[tuple, dict] = {}  # toda chamada em execução, pela chave (nome, argumentos)
        self._next = 1

    def run(self, name: str, args: dict | None, call: Callable[[], str], title: str = "", group: str = "") -> str:
        key = (name, json.dumps(args or {}, sort_keys=True, ensure_ascii=False, default=str))
        with self._lock:
            same = self._running.get(key)
            if same is not None:
                return (f"já está rodando: “{same['title']}” continua em andamento. Não chame de novo; o sistema "
                        "avisa quando terminar")
            task = {"id": 0, "title": title or name, "status": "rodando", "step": "", "value": None,
                    "started": self.clock(), "ended": None, "result": "", "background": False, "owner": self}
            self._running[key] = task
            lock = self._groups.setdefault(group, threading.Lock()) if group else None
        finished = threading.Event()

        def work():
            _current.set(task)
            try:
                if lock is not None:
                    with lock:                # um recurso por vez (o navegador, por exemplo)
                        result = str(call())
                else:
                    result = str(call())
                failed = result.startswith("erro")
            except Exception as exc:
                result, failed = f"erro: {exc}", True
            with self._lock:
                task["result"], task["ended"] = result, self.clock()
                task["status"] = "falhou" if failed else "pronta"
                self._running.pop(key, None)
                in_background = task["background"]
                finished.set()
            if in_background:
                self._finish(task)

        threading.Thread(target=work, daemon=True, name=f"viv-tarefa-{name}").start()
        finished.wait(self.after)
        with self._lock:
            if finished.is_set():
                return task["result"]
            task["background"], task["id"] = True, self._next
            self._next += 1
            self._tasks.append(task)
        BUS.emit("progress", "", value=None, done=True)      # a barra da conversa não é mais desta tarefa
        self._publish()
        return (f"em segundo plano: tarefa {task['id']} ({task['title']}) continua rodando. Diga ao usuário em uma "
                "frase que você está cuidando disso e siga a conversa normalmente. O sistema avisa quando terminar; "
                "não chame esta ferramenta de novo. Para saber o andamento, use tarefas_andamento.")

    def _finish(self, task: dict) -> None:
        with self._lock:
            done = [t for t in self._tasks if t["status"] != "rodando"]
            for old in done[:-HISTORY]:
                self._tasks.remove(old)
        self._publish()
        if self.on_done is not None:
            self.on_done(self._view(task))

    def _view(self, task: dict) -> dict:
        end = task["ended"] if task["ended"] is not None else self.clock()
        return {"id": task["id"], "title": task["title"], "status": task["status"], "step": task["step"],
                "value": task["value"], "seconds": int(end - task["started"]), "result": task["result"][:RESULT_LIMIT]}

    def snapshot(self) -> list[dict]:
        """As tarefas de fundo: rodando e as terminadas há pouco."""
        with self._lock:
            return [self._view(task) for task in self._tasks]

    def _publish(self) -> None:
        BUS.emit("tasks", "", items=[{k: t[k] for k in ("id", "title", "step", "value")}
                                     for t in self.snapshot() if t["status"] == "rodando"])
