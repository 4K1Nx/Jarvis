"""Janela do CMD em que um agente de código programa um projeto da Viv.

    python scripts/agente_runner.py <pasta do projeto> <claude|codex|ollama> [modelo]

O pedido vem de .viv/agente_pedido.txt. O progresso aparece nesta janela e vai para .viv/agente.log;
o estado (trabalhando, terminou, falhou, sessão para continuar) fica em .viv/agente.json, que a Viv lê.
Aberto pela ferramenta agente_programar (viv/tools/agente.py), depois da confirmação do usuário.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OLLAMA = "http://127.0.0.1:11434"


def short(value, size=160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= size else text[:size] + "…"


def _lines(cmd, folder: Path, request: str):
    """Roda o agente com o pedido na entrada padrão e devolve as linhas da saída, uma a uma."""
    process = subprocess.Popen(cmd, cwd=folder, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONUTF8="1"))
    process.stdin.write(request)
    process.stdin.close()
    yield from process.stdout
    yield process.wait()                       # o último item é o código de saída


def run_claude(folder: Path, request: str, session, model, say, keep):
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("Claude Code não está instalado (npm install -g @anthropic-ai/claude-code)")
    cmd = [exe, "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits",
           "--allowedTools", "Bash"]
    cmd += ["--resume", session] if session else []
    cmd += ["--model", model] if model else []
    summary, failed = "", False
    for line in _lines(cmd, folder, request):
        if isinstance(line, int):
            if line and not summary:
                raise RuntimeError(f"o Claude Code terminou com código {line}")
            break
        try:
            event = json.loads(line)
        except ValueError:
            line.strip() and say(line.rstrip())
            continue
        if event.get("session_id") and event["session_id"] != session:
            session = keep(event["session_id"])
        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text" and block.get("text", "").strip():
                    say(f"\n{block['text'].strip()}\n")
                elif block.get("type") == "tool_use":
                    say(f"> {block.get('name')}: {short(block.get('input'))}")
        elif event.get("type") == "result":
            summary, failed = str(event.get("result") or ""), bool(event.get("is_error"))
    if failed:
        raise RuntimeError(summary or "o Claude Code não conseguiu terminar")
    return summary, session


def run_codex(folder: Path, request: str, session, model, say, keep):
    exe = shutil.which("codex")
    if not exe:
        raise RuntimeError("Codex não está instalado (npm install -g @openai/codex, depois codex login)")
    cmd = [exe, "exec", "--json", "--full-auto", "--skip-git-repo-check"]
    cmd += ["--model", model] if model else []
    cmd += ["resume", session] if session else []
    cmd.append("-")
    summary, error = "", ""
    for line in _lines(cmd, folder, request):
        if isinstance(line, int):
            if line and not summary:
                raise RuntimeError(error or f"o Codex terminou com código {line}")
            break
        try:
            event = json.loads(line)
        except ValueError:
            line.strip() and say(line.rstrip())
            continue
        kind, item = event.get("type", ""), event.get("item") or {}
        found = event.get("thread_id") or event.get("session_id")
        if found and found != session:
            session = keep(found)
        if kind == "item.completed":
            if item.get("type") == "agent_message":
                summary = str(item.get("text") or "")
                say(f"\n{summary.strip()}\n")
            elif item.get("type") == "command_execution":
                say(f"> comando: {short(item.get('command'))} (código {item.get('exit_code')})")
            elif item.get("type") == "file_change":
                say("> arquivos: " + ", ".join(f"{c.get('kind')} {c.get('path')}" for c in item.get("changes", [])))
        elif kind in ("turn.failed", "error"):
            error = short((event.get("error") or {}).get("message") or event.get("message") or line, 300)
            say(f"! {error}")
    return summary, session


def _ollama_ready(say) -> list[str]:
    def models():
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=3) as response:
            return [m["name"] for m in json.load(response).get("models", [])]
    try:
        return models()
    except OSError:
        exe = shutil.which("ollama") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe")
        say("> iniciando o Ollama")
        subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for _ in range(30):
            time.sleep(1)
            try:
                return models()
            except OSError:
                pass
    raise RuntimeError("o Ollama não respondeu; abra o Ollama e tente de novo")


def run_ollama(folder: Path, request: str, session, model, say, keep):
    """Modelo local: usa o mesmo construtor do codigo_criar, com as respostas vindo do Ollama."""
    from viv.tools import _llm, code
    names = _ollama_ready(say)
    if model not in names and f"{model}:latest" not in names:
        raise RuntimeError(f"o modelo {model} não está baixado; no CMD rode: ollama pull {model} "
                           f"(baixados: {', '.join(names) or 'nenhum'})")

    def ask(_ctx, prompt, as_json=False):
        body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": True,
                "options": {"num_ctx": 32768}, **({"format": "json"} if as_json else {})}
        request_ = urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps(body).encode(),
                                          headers={"Content-Type": "application/json"})
        pieces = []
        with urllib.request.urlopen(request_, timeout=3600) as response:
            for raw in response:
                event = json.loads(raw)
                if event.get("error"):
                    raise RuntimeError(f"Ollama: {event['error']}")
                piece = event.get("message", {}).get("content", "")
                pieces.append(piece)
                print(piece, end="", flush=True)        # o código aparece sendo escrito na janela
        print()
        text = "".join(pieces)
        return _llm.parse_json(text) if as_json else text

    code.progress = lambda label, value=None: say(f"> {label}")
    result = code.build(None, folder, request, ask=ask)
    lines = [result["resumo"], "Arquivos: " + (", ".join(result["arquivos"]) or "nenhum")]
    if result["erros"]:
        lines.append("Ficaram erros de sintaxe: " + "; ".join(result["erros"])[:400])
    return "\n".join(lines), session


RUNNERS = {"claude": run_claude, "codex": run_codex, "ollama": run_ollama}


def main(folder: Path, agent: str, model: str = "") -> int:
    from viv.tools import code
    viv_dir = folder / ".viv"
    state_path, log_path = viv_dir / "agente.json", viv_dir / "agente.log"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}

    def save():
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    def keep(session):
        """Grava a sessão assim que aparece: se a Viv interromper, a próxima instrução continua dela."""
        state["sessao"] = session
        save()
        return session

    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(f"Viv programando: {folder.name} ({agent})")
    request = (viv_dir / "agente_pedido.txt").read_text(encoding="utf-8")
    with open(log_path, "a", encoding="utf-8") as log:
        def say(line: str):
            print(line, flush=True)
            log.write(line + "\n")
            log.flush()

        say(f"\n=== {time.strftime('%d/%m %H:%M')} · {agent} · {folder.name} ===")
        say(short(request.split("Pedido do usuário:")[-1], 400))
        state.update(agente=agent, estado="trabalhando", inicio=time.time(), fim=None, resumo="", pid=os.getpid())
        save()
        try:
            summary, session = RUNNERS[agent](folder, request, state.get("sessao"), model, say, keep)
            command = ""
            kept = []
            for line in summary.strip().splitlines():
                if line.strip().upper().startswith("EXECUTAR:"):
                    command = line.split(":", 1)[1].strip().strip("`")
                else:
                    kept.append(line)
            if command:
                code._save_meta(folder, {**code._meta(folder), "executar": command})
            state.update(estado="terminou", resumo="\n".join(kept).strip()[-2000:], sessao=session)
            say("\n=== terminou ===")
        except Exception as exc:
            state.update(estado="falhou", resumo=str(exc)[:1000])
            say(f"\n=== falhou: {exc} ===")
        state["fim"] = time.time()
        save()
        code._commit(folder, "agente: " + short(request.split("Pedido do usuário:")[-1], 60))
    try:
        input("\nPressione Enter para fechar esta janela.")
    except EOFError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""))
