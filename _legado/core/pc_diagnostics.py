"""Read-only resource report; never terminates processes or changes settings."""
import psutil
from pathlib import Path


def diagnose():
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage(Path.home().anchor)
    rows = []
    for process in psutil.process_iter(['name', 'memory_info']):
        try:
            info = process.info
            if info.get('memory_info'):
                rows.append((info['memory_info'].rss, info.get('name') or 'Processo'))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    top = sorted(rows, reverse=True)[:5]
    result = [f'RAM: {ram.percent:.0f}%. Disco do sistema: {disk.percent:.0f}% ocupado.',
              'Maiores processos por RAM: '+', '.join(f'{name}: {size/1024**2:.0f} MB' for size,name in top)+'.']
    if ram.percent >= 80:
        result.append('RAM elevada: salve seu trabalho e revise os aplicativos abertos antes de pedir para fechar um deles.')
    if disk.percent >= 90:
        result.append('Pouco espaço livre: revise arquivos grandes e faça backup antes de remover qualquer conteúdo.')
    if ram.percent < 80 and disk.percent < 90:
        result.append('Esta amostra não indica pressão elevada de RAM ou espaço em disco; não avalia todos os gargalos.')
    result.append('Nenhuma configuração foi alterada e nenhum processo foi encerrado.')
    return ' '.join(result)
