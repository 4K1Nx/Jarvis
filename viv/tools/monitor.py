"""Monitoramento e desempenho do PC: painel ao vivo, alertas, velocidade da internet, programas que iniciam
com o Windows e plano de energia.

Nada aqui apaga arquivos (isso é de viv/tools/optimize.py). Desativar um programa da inicialização usa a mesma
chave do Gerenciador de Tarefas (StartupApproved), então dá para reativar por aqui ou por lá.
"""
import os
import statistics
import subprocess
import threading
import time
import winreg

from viv.tools import charts
from viv.tools.registry import progress, tool

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
SPEED = "https://speed.cloudflare.com"
RESOURCES = {"cpu": "CPU", "memoria": "Memória", "disco": "Disco"}
PLANS = {"equilibrado": "381b4222-f694-41f0-9685-ff5bb260df2e", "desempenho": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
         "economia": "a1841308-3541-4fab-bc81-f71556f20b4a"}


# ---- leitura do sistema -----------------------------------------------------------
def snapshot(interval: float = 0.4) -> dict:
    """Uso atual: CPU, memória, disco do sistema (em %), rede em Mbps e bateria."""
    import psutil
    before, start = psutil.net_io_counters(), time.monotonic()
    cpu = psutil.cpu_percent(interval=interval)
    after, elapsed = psutil.net_io_counters(), max(time.monotonic() - start, 1e-3)
    ram, disk = psutil.virtual_memory(), psutil.disk_usage(os.path.abspath(os.sep))
    battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    return {"cpu": cpu, "memoria": ram.percent, "disco": disk.percent,
            "ram_gb": ram.used / 1e9, "ram_total_gb": ram.total / 1e9, "disco_livre_gb": disk.free / 1e9,
            "down_mbps": (after.bytes_recv - before.bytes_recv) * 8 / 1e6 / elapsed,
            "up_mbps": (after.bytes_sent - before.bytes_sent) * 8 / 1e6 / elapsed,
            "bateria": battery.percent if battery else None}


def gauges(data: dict) -> dict:
    items = [{"label": "CPU", "value": data["cpu"], "max": 100, "unit": "%"},
             {"label": "Memória", "value": data["memoria"], "max": 100, "unit": "%"},
             {"label": "Disco usado", "value": data["disco"], "max": 100, "unit": "%"}]
    if data.get("bateria") is not None:
        items.append({"label": "Bateria", "value": data["bateria"], "max": 100, "unit": "%"})
    return charts.chart("medidores", items)


def describe(data: dict) -> str:
    text = (f"CPU {data['cpu']:.0f}%, memória {data['memoria']:.0f}% ({data['ram_gb']:.1f} de {data['ram_total_gb']:.0f} GB), "
            f"disco {data['disco']:.0f}% usado ({data['disco_livre_gb']:.0f} GB livres), "
            f"rede {data['down_mbps']:.1f} Mbps baixando e {data['up_mbps']:.1f} Mbps enviando")
    return text + (f", bateria {data['bateria']:.0f}%" if data.get("bateria") is not None else "")


class Monitor:
    """Painel ao vivo e alertas, numa thread. Um painel e uma lista de alertas por vez."""
    def __init__(self, read=snapshot, notify=None, show=charts.show, clock=time.monotonic, wait=None):
        self.read, self.notify, self.show, self.clock = read, notify, show, clock
        self._stop = threading.Event()
        self.wait = wait or self._stop.wait
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.panel_until = 0.0
        self.alerts: list[dict] = []          # {recurso, limite, ate, desde, avisado}

    def _ensure(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(target=self._run, daemon=True, name="viv-monitor")
                self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set() and self.step():
            self.wait(2.0)

    def step(self) -> bool:
        """Uma leitura: atualiza o painel e confere os alertas. Devolve False quando não há mais o que fazer."""
        now = self.clock()
        with self._lock:
            panel = now < self.panel_until
            self.alerts = [a for a in self.alerts if now < a["ate"]]
            alerts = list(self.alerts)
        if not panel and not alerts:
            return False
        data = self.read()
        if panel:
            self.show("PC ao vivo", gauges(data), body=f"Rede: {data['down_mbps']:.1f} Mbps ↓  {data['up_mbps']:.1f} Mbps ↑", live="pc")
        for alert in alerts:
            value = data[alert["recurso"]]
            if value < alert["limite"]:
                alert["desde"], alert["avisado"] = None, False
                continue
            alert["desde"] = alert["desde"] if alert["desde"] is not None else now
            if not alert["avisado"] and now - alert["desde"] >= alert["segundos"]:
                alert["avisado"] = True
                if self.notify is not None:
                    self.notify(f"Alerta do monitor do PC: {RESOURCES[alert['recurso']]} em {value:.0f}%, acima do limite de "
                                f"{alert['limite']:.0f}% que o usuário pediu para vigiar. Avise-o em uma frase e, se for "
                                "memória ou CPU, ofereça ver os processos mais pesados.")
        return True

    def panel(self, seconds: float) -> None:
        with self._lock:
            self.panel_until = self.clock() + seconds
        self._ensure()

    def watch(self, resource: str, limit: float, minutes: float, sustained: float = 20.0) -> None:
        with self._lock:
            self.alerts = [a for a in self.alerts if a["recurso"] != resource]
            self.alerts.append({"recurso": resource, "limite": limit, "ate": self.clock() + minutes * 60,
                                "segundos": sustained, "desde": None, "avisado": False})
        self._ensure()

    def stop(self) -> int:
        with self._lock:
            count, self.alerts, self.panel_until = len(self.alerts), [], 0.0
        self._stop.set()
        return count


_monitor: Monitor | None = None


def monitor(ctx) -> Monitor:
    global _monitor
    if _monitor is None:
        _monitor = Monitor()
    _monitor.notify = getattr(ctx, "notify", None)
    return _monitor


@tool("system_monitorar", "Abrir um painel ao vivo na tela com CPU, memória, disco e rede, atualizado a cada dois segundos. "
      "Use quando o usuário pedir para monitorar o PC, acompanhar o desempenho ou ver o uso em tempo real.",
      {"segundos": {"type": "integer", "description": "por quanto tempo manter o painel (padrão 60, máximo 600)", "required": False}},
      card=False, title="Monitor do PC")
def system_monitorar(segundos=60, ctx=None):
    data = snapshot()
    charts.show("PC ao vivo", gauges(data), body=f"Rede: {data['down_mbps']:.1f} Mbps ↓  {data['up_mbps']:.1f} Mbps ↑", live="pc")
    monitor(ctx).panel(max(10, min(600, int(segundos or 60))))
    return f"painel ao vivo na tela. Agora: {describe(data)}. Comente só o que chamar atenção."


@tool("monitor_alerta", "Vigiar um recurso do PC em segundo plano e avisar o usuário em voz alta se passar de um limite por "
      "mais de 20 segundos. Ex.: avisar se a memória passar de 90%.",
      {"recurso": {"type": "string", "description": "cpu | memoria | disco"},
       "limite": {"type": "number", "description": "percentual de 1 a 100"},
       "minutos": {"type": "integer", "description": "por quanto tempo vigiar (padrão 120, máximo 720)", "required": False}},
      title="Alerta do monitor")
def monitor_alerta(recurso, limite, minutos=120, ctx=None):
    resource = str(recurso).casefold().strip().replace("ó", "o").replace("ram", "memoria")
    if resource not in RESOURCES:
        raise ValueError("recurso: use cpu, memoria ou disco")
    limit = float(limite)
    if not 1 <= limit <= 100:
        raise ValueError("o limite é um percentual de 1 a 100")
    minutes = max(1, min(720, int(minutos or 120)))
    monitor(ctx).watch(resource, limit, minutes)
    return f"vigiando {RESOURCES[resource]}: aviso se passar de {limit:.0f}% nas próximas {minutes} minutos"


@tool("monitor_parar", "Parar o painel ao vivo e todos os alertas do monitor do PC.", {}, title="Monitor do PC")
def monitor_parar(ctx=None):
    count = monitor(ctx).stop()
    return f"monitor parado ({count} alerta(s) cancelado(s))"


# ---- velocidade da internet -----------------------------------------------------------
def _ping(http) -> float:
    start = time.monotonic()
    http.get(f"{SPEED}/__down?bytes=0", timeout=5)
    return (time.monotonic() - start) * 1000


def _download(http, seconds: float) -> tuple[int, float]:
    total, start = 0, time.monotonic()
    with http.stream("GET", f"{SPEED}/__down?bytes=200000000", timeout=10) as reply:
        for chunk in reply.iter_bytes(65536):
            total += len(chunk)
            if time.monotonic() - start >= seconds:
                break
    return total, time.monotonic() - start


def _upload(http, seconds: float) -> tuple[int, float]:
    sent, start, block = [0], time.monotonic(), bytes(65536)

    def body():
        while time.monotonic() - start < seconds and sent[0] < 100_000_000:
            sent[0] += len(block)
            yield block
    http.post(f"{SPEED}/__up", content=body(), timeout=seconds + 15)
    return sent[0], time.monotonic() - start


def speed_test(seconds: float = 6.0, ping=None, download=None, upload=None) -> dict:
    """Mede latência, download e upload. As três medidas são injetáveis para teste."""
    import httpx
    with httpx.Client(headers={"User-Agent": "assistente-pessoal/1.0"}) as http:
        progress("Medindo a latência", 0.05)
        pings = []
        for _ in range(4):
            try:
                pings.append((ping or _ping)(http))
            except Exception:
                pass
        if not pings:
            raise RuntimeError("não consegui falar com o servidor de teste; a internet pode estar fora do ar")
        progress("Medindo o download", 0.2)
        got, took = (download or _download)(http, seconds)
        progress("Medindo o upload", 0.6)
        try:
            sent, lasted = (upload or _upload)(http, seconds)
        except Exception:
            sent, lasted = 0, 1.0                 # alguns provedores bloqueiam o teste de envio
    return {"ping_ms": statistics.median(pings), "down_mbps": got * 8 / 1e6 / max(took, 1e-3),
            "up_mbps": sent * 8 / 1e6 / max(lasted, 1e-3)}


def judge(down: float) -> str:
    if down < 5:
        return "lenta: vídeo em alta definição e downloads grandes vão sofrer"
    if down < 25:
        return "razoável: dá para vídeo em HD e chamadas, mas downloads grandes demoram"
    if down < 100:
        return "boa para streaming em 4K, chamadas e jogos"
    return "muito rápida"


@tool("rede_velocidade", "Medir a velocidade da internet: download, upload e latência (ping). Leva uns 15 segundos e mostra "
      "o resultado em medidores na tela. Use quando o usuário perguntar da internet, da conexão ou reclamar de lentidão.",
      {}, card=False, title="Teste de velocidade")
def rede_velocidade(ctx=None):
    result = speed_test()
    top = max(100.0, result["down_mbps"] * 1.25, result["up_mbps"] * 1.25)
    charts.show("Velocidade da internet", charts.chart("medidores", [
        {"label": "Download", "value": result["down_mbps"], "max": top, "unit": " Mbps"},
        {"label": "Upload", "value": result["up_mbps"], "max": top, "unit": " Mbps"},
        {"label": "Latência", "value": result["ping_ms"], "max": 200, "unit": " ms"}]))
    upload = f"{result['up_mbps']:.1f} Mbps" if result["up_mbps"] else "não foi possível medir"
    return (f"download {result['down_mbps']:.1f} Mbps, upload {upload}, latência {result['ping_ms']:.0f} ms. "
            f"Conexão {judge(result['down_mbps'])}. Resultado na tela.")


# ---- processos mais pesados -----------------------------------------------------------
@tool("system_pesados", "Ver quais programas estão pesando no PC agora, por uso de CPU e de memória, num gráfico de barras. "
      "Use quando o computador estiver lento ou o usuário perguntar o que está consumindo recursos.",
      {}, card=False, title="Processos pesados")
def system_pesados(ctx=None):
    import psutil
    procs = list(psutil.process_iter(["name", "memory_info"]))
    for proc in procs:
        try:
            proc.cpu_percent(None)
        except psutil.Error:
            pass
    time.sleep(1.0)
    usage: dict[str, list[float]] = {}
    cores = psutil.cpu_count() or 1
    for proc in procs:
        try:
            name = (proc.info["name"] or "?").removesuffix(".exe")
            cpu, ram = proc.cpu_percent(None) / cores, proc.info["memory_info"].rss / 1e6
        except (psutil.Error, AttributeError):
            continue
        if name not in ("System Idle Process", "Idle"):
            entry = usage.setdefault(name, [0.0, 0.0])
            entry[0], entry[1] = entry[0] + cpu, entry[1] + ram
    by_ram = sorted(usage.items(), key=lambda kv: kv[1][1], reverse=True)[:6]
    by_cpu = sorted(usage.items(), key=lambda kv: kv[1][0], reverse=True)[:3]
    charts.show("O que está pesando", charts.chart("barras", [{"label": n, "value": v[1]} for n, v in by_ram], " MB"),
                body="CPU agora: " + ", ".join(f"{n} {v[0]:.0f}%" for n, v in by_cpu))
    return ("memória: " + ", ".join(f"{n} {v[1]:.0f} MB" for n, v in by_ram) + ". CPU: "
            + ", ".join(f"{n} {v[0]:.0f}%" for n, v in by_cpu) + ". Para fechar um deles, system_kill (pede confirmação).")


# ---- inicialização do Windows -----------------------------------------------------------
def startup_entries() -> list[dict]:
    """Programas da chave Run do usuário e da máquina, com o estado (ativo ou desativado)."""
    found = []
    for hive, scope in ((winreg.HKEY_CURRENT_USER, "usuario"), (winreg.HKEY_LOCAL_MACHINE, "maquina")):
        disabled = {}
        try:
            with winreg.OpenKey(hive, APPROVED) as key:
                for i in range(winreg.QueryInfoKey(key)[1]):
                    name, data, _ = winreg.EnumValue(key, i)
                    disabled[name] = isinstance(data, bytes) and len(data) > 0 and data[0] % 2 == 1
        except OSError:
            pass
        try:
            with winreg.OpenKey(hive, RUN) as key:
                for i in range(winreg.QueryInfoKey(key)[1]):
                    name, command, _ = winreg.EnumValue(key, i)
                    found.append({"nome": name, "comando": str(command)[:120], "escopo": scope, "ativo": not disabled.get(name, False)})
        except OSError:
            pass
    return sorted(found, key=lambda e: e["nome"].casefold())


def set_startup(name: str, enabled: bool, entries=None, write=None) -> dict:
    wanted = str(name).casefold().strip()
    matches = [e for e in (entries if entries is not None else startup_entries()) if wanted and wanted in e["nome"].casefold()]
    exact = [e for e in matches if e["nome"].casefold() == wanted]
    if len(exact) == 1:
        matches = exact
    if len(matches) != 1:
        raise ValueError("não achei esse programa na inicialização" if not matches else
                         "mais de um programa combina: " + ", ".join(e["nome"] for e in matches))
    entry = matches[0]

    def registry_write(item, flag):
        hive = winreg.HKEY_CURRENT_USER if item["escopo"] == "usuario" else winreg.HKEY_LOCAL_MACHINE
        with winreg.CreateKeyEx(hive, APPROVED, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, item["nome"], 0, winreg.REG_BINARY, bytes([2 if flag else 3]) + bytes(11))
    try:
        (write or registry_write)(entry, enabled)
    except PermissionError:
        raise PermissionError(f"{entry['nome']} é uma inicialização de todos os usuários: só dá para mudar abrindo a Viv "
                              "como administrador, ou pelo Gerenciador de Tarefas") from None
    return entry


@tool("system_inicializacao", "Listar os programas que abrem junto com o Windows e se cada um está ativo. Muitos deles "
      "deixam o PC lento ao ligar.", {}, card=False, title="Inicialização do Windows")
def system_inicializacao(ctx=None):
    from viv.bus import BUS
    entries = startup_entries()
    rows = ["Programa | Estado"] + [f"{e['nome']} | {'ativo' if e['ativo'] else 'desativado'}" for e in entries]
    BUS.emit("card", "Abrem com o Windows", kind="content", format="tabela", body="\n".join(rows), ok=True)
    active = [e["nome"] for e in entries if e["ativo"]]
    return (f"{len(active)} programa(s) ativos na inicialização: {', '.join(active[:15])}. Lista na tela. Para desativar um, "
            "use system_inicializacao_definir (pede confirmação); sugira só o que o usuário reconhecer que não precisa.")


def _confirm_startup(args: dict) -> str:
    entry = set_startup(args.get("nome", ""), True, write=lambda item, flag: None)       # só valida e acha o nome real
    turn = "Ativar" if str(args.get("ativo", "")).casefold().strip() in ("true", "sim", "1", "ativar") or args.get("ativo") is True else "Desativar"
    return f"{turn} {entry['nome']} na inicialização do Windows? Dá para desfazer depois."


@tool("system_inicializacao_definir", "Ativar ou desativar um programa da inicialização do Windows (o programa continua "
      "instalado; só deixa de abrir sozinho ao ligar). Exige confirmação.",
      {"nome": {"type": "string", "description": "nome do programa, como aparece em system_inicializacao"},
       "ativo": {"type": "boolean", "description": "true para abrir com o Windows, false para não abrir"}},
      dangerous=True, card=False, title="Inicialização do Windows", confirm=_confirm_startup)
def system_inicializacao_definir(nome, ativo, ctx=None):
    enabled = ativo is True or str(ativo).casefold().strip() in ("true", "sim", "1", "ativar")
    entry = set_startup(nome, enabled)
    return f"{entry['nome']} {'volta a abrir' if enabled else 'não abre mais'} junto com o Windows"


# ---- plano de energia -----------------------------------------------------------
def _powercfg(*args: str) -> str:
    out = subprocess.run(["powercfg", *args], capture_output=True, timeout=20, creationflags=NO_WINDOW)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout).decode("cp850", errors="replace").strip()[:200] or "powercfg falhou")
    return out.stdout.decode("cp850", errors="replace")


@tool("system_energia", "Ver ou trocar o plano de energia do Windows: desempenho (mais rápido, gasta mais), equilibrado "
      "(padrão) ou economia. Sem plano, só informa o atual.",
      {"plano": {"type": "string", "description": "desempenho | equilibrado | economia; vazio só consulta", "required": False}},
      title="Plano de energia")
def system_energia(plano="", ctx=None, run=None):
    run = run or _powercfg
    wanted = str(plano or "").casefold().strip()
    if wanted:
        if wanted not in PLANS:
            raise ValueError("plano: use desempenho, equilibrado ou economia")
        try:
            run("/setactive", PLANS[wanted])
        except RuntimeError:
            raise RuntimeError(f"este computador não tem o plano {wanted} disponível") from None
    current = run("/getactivescheme")
    name = next((label for label, guid in PLANS.items() if guid in current.casefold()), "")
    shown = name or current.split("(")[-1].split(")")[0].strip() or "desconhecido"
    return f"plano de energia {'agora' if wanted else 'atual'}: {shown}"
