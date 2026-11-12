"""Exact process matching; Minecraft Java must be identified as a client."""
def matches_process(request, executable, command):
    wanted = request.strip().casefold().removesuffix('.exe')
    exe = (executable or '').casefold()
    if not wanted:
        return False
    if wanted == 'minecraft':
        if exe in ('minecraft.exe', 'minecraft.windows.exe'):
            return True
        if exe not in ('java.exe', 'javaw.exe'):
            return False
        args = [str(a).casefold() for a in (command or [])]
        return (any(a in ('net.minecraft.client.main.main',
                         'net.fabricmc.loader.impl.launch.knot.knotclient',
                         'net.fabricmc.loader.launch.knot.knotclient') for a in args)
                or any(args[i] == '--launchtarget' and args[i+1] in ('forgeclient','neoforgeclient')
                       for i in range(len(args)-1)))
    return exe.removesuffix('.exe') == wanted


def terminate_named(name, processes):
    """Caller must enforce owner verification and confirmation first."""
    closed = failed = 0
    for process in processes:
        info = process.info
        if matches_process(name, info.get('name'), info.get('cmdline')):
            try:
                process.terminate()
                process.wait(timeout=3)
                closed += 1
            except Exception:
                failed += 1
    if not closed and not failed:
        return 'Nenhum processo correspondente encontrado; nada foi encerrado.'
    return f'Processos encerrados: {closed}. Falhas ou encerramento não confirmado: {failed}.'
