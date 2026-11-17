"""Controle do sistema: energia, processos, volume e diagnóstico."""
import os
import subprocess

from viv.tools.registry import tool

IS_WIN = os.name == "nt"


@tool("system_power", "Desligar, reiniciar, suspender, bloquear ou encerrar a sessão do PC. Exige confirmação.",
      {"action": {"type": "string", "description": "shutdown | restart | sleep | lock | logoff"},
       "delay_seconds": {"type": "integer", "required": False}}, dangerous=True, title="Energia")
def power(action, delay_seconds=15, ctx=None):
    action = action.lower().strip()
    cmds = {
        "shutdown": ["shutdown", "/s", "/t", str(int(delay_seconds))],
        "restart": ["shutdown", "/r", "/t", str(int(delay_seconds))],
        "logoff": ["shutdown", "/l"],
        "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
        "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
    }
    if action not in cmds:
        raise ValueError(f"ação de energia desconhecida: {action}")
    if not IS_WIN:
        return f"{action} simulado (não é Windows)"
    subprocess.Popen(cmds[action])
    if action in ("shutdown", "restart"):
        return f"{action} agendado para {delay_seconds}s; peça para cancelar se quiser abortar"
    return f"{action} executado"


@tool("system_cancel_shutdown", "Cancelar um desligamento ou reinício agendado.", {}, title="Cancelar desligamento")
def cancel_shutdown(ctx=None):
    if IS_WIN:
        subprocess.Popen(["shutdown", "/a"])
    return "desligamento cancelado"


@tool("system_status", "Informar uso de CPU, memória, disco, rede e bateria agora, com medidores na tela.", {},
      card=False, title="Estado do sistema")
def status(ctx=None):
    from viv.tools import charts, monitor
    data = monitor.snapshot(0.2)
    charts.show("Estado do PC", monitor.gauges(data))            # os números aparecem em medidores na tela
    return monitor.describe(data) + ". Medidores na tela; comente só o que chamar atenção."


@tool("system_processes", "Listar os processos que mais usam memória.",
      {"top": {"type": "integer", "required": False}}, title="Processos")
def processes(top=8, ctx=None):
    import psutil
    procs = sorted(psutil.process_iter(["name", "memory_info"]),
                   key=lambda p: p.info["memory_info"].rss if p.info.get("memory_info") else 0,
                   reverse=True)[:int(top)]
    return ", ".join(f"{p.info['name']} {p.info['memory_info'].rss / 1e6:.0f} MB" for p in procs)


@tool("system_kill", "Encerrar um aplicativo pelo nome. Exige confirmação.",
      {"name": {"type": "string"}}, dangerous=True, title="Encerrar aplicativo")
def kill(name, ctx=None):
    import psutil
    from viv.tools._process_control import terminate_named
    return terminate_named(name, psutil.process_iter(["name", "cmdline"]))


@tool("system_volume", "Definir o volume principal de 0 a 100.", {"percent": {"type": "integer"}}, title="Volume")
def volume(percent, ctx=None):
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    level = max(0, min(100, int(percent)))
    device = AudioUtilities.GetSpeakers()
    iface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    cast(iface, POINTER(IAudioEndpointVolume)).SetMasterVolumeLevelScalar(level / 100.0, None)
    return f"volume em {level}%"
