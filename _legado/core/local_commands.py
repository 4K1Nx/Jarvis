"""Explicit Portuguese local commands. No fuzzy dispatch or arbitrary shell generation."""
import re
from datetime import datetime

def parse(text):
    text=text.strip().rstrip('.!?').strip()
    text=re.sub(r'^(?:(?:ei|oi|olá),?\s+)?(?:viv|vivi|vive)[,:]?\s+', '', text, flags=re.I)
    text=re.sub(r',?\s+por favor$', '', text, flags=re.I)
    lower=text.casefold()
    if lower in ('o que você ainda não consegue fazer','liste suas limitações','quais são suas pendências'):
        return {'gaps':True}
    if lower in ('está me ouvindo','tá me ouvindo','você está me ouvindo','você tá me ouvindo'):
        return {'reply':'Sim, ouvi e transcrevi sua fala. Estou no modo de comandos locais.'}
    if lower in ('que horas são','qual a hora'):
        return {'reply':datetime.now().strftime('Agora são %H horas e %M minutos.')}
    if lower in ('o que você pode fazer','ajuda','quais comandos estão disponíveis'):
        return {'reply':'Posso pesquisar, criar lembretes, abrir aplicativos, fechar um aplicativo com confirmação, ler, criar e editar arquivos de texto com confirmação. Também leio texto acessível da janela ativa e diagnostico RAM e disco. Imagens e conversa livre precisam de um modelo disponível.'}
    if lower in ('observe minha tela','olhe minha tela','o que está na minha tela','veja minha tela','leia minha tela'):
        return {'tool':'vision.read_screen_local','args':{}}
    if lower in ('otimize meu pc','otimizar o pc','otimize o pc','diagnóstico do pc','como está meu pc'):
        return {'tool':'system.diagnose','args':{},'prefix':'Diagnóstico de uso atual; nenhuma configuração foi alterada. '}
    if lower in ('liste meus lembretes','quais são meus lembretes','listar lembretes'):
        return {'tool':'reminder.list','args':{}}
    # Normalize the equally natural task-first form; preserve the full task.
    reminder_match=re.fullmatch(r'(?:me lembre|lembre-me|lembre me) (?:de |para )?(.+?) (?:daqui a|em) (\d+|um|uma|dois|duas|três|tres|quatro|cinco|seis|sete|oito|nove|dez|quinze|vinte|trinta|sessenta) (segundos?|minutos?|horas?)',text,re.I)
    if reminder_match:
        task,number,unit=reminder_match.groups()
        text=f'me lembre em {number} {unit} de {task}'
    match=re.fullmatch(r'(?:me lembre|lembre-me|lembre me) (?:daqui a|em) (\d+|um|uma|dois|duas|três|tres|quatro|cinco|seis|sete|oito|nove|dez|quinze|vinte|trinta|sessenta) (segundos?|minutos?|horas?) (?:de |para )?(.+)',text,re.I)
    if match:
        number,unit,reminder=match.groups()
        numbers={'um':1,'uma':1,'dois':2,'duas':2,'três':3,'tres':3,'quatro':4,'cinco':5,'seis':6,'sete':7,'oito':8,'nove':9,'dez':10,'quinze':15,'vinte':20,'trinta':30,'sessenta':60}
        amount=int(number) if number.isdigit() else numbers[number.casefold()]
        seconds=amount*(1 if unit.casefold().startswith('segundo') else 60 if unit.casefold().startswith('minuto') else 3600)
        if not 1<=seconds<=366*86400:return {'reply':'Use um prazo entre um segundo e um ano.'}
        return {'tool':'reminder.set','args':{'minutes':seconds/60,'text':reminder}}
    match=re.fullmatch(r'(?:pesquise|pesquisa|busque|busca)(?: na internet)?(?: sobre)?\s+(.+)',text,re.I)
    if match:return {'tool':'web.search','args':{'query':match[1]}}
    if re.fullmatch(r'(?:abra|abrir|abre) (?:a )?calculadora',text,re.I):
        return {'tool':'desktop.open_calculator','args':{}}
    match=re.fullmatch(r'(?:abra|abrir) (?:o |a )?(bloco de notas|calculadora|explorador de arquivos)',text,re.I)
    if match:return {'tool':'desktop.launch_app','args':{'app':{'bloco de notas':'notepad.exe','calculadora':'calc.exe','explorador de arquivos':'explorer.exe'}[match[1].casefold()]}}
    match=re.fullmatch(r'(?:feche|fechar|encerre) (?:o |a )?([\w. -]{1,60})(?: pra mim)?',text,re.I)
    if match:return {'tool':'system.kill','args':{'name':re.sub(r' pra mim$','',match[1],flags=re.I)}}
    match=re.fullmatch(r'(?:abra|abrir) (?:o )?arquivo "([^"]+)"',text,re.I)
    if match:return {'tool':'files.open','args':{'path':match[1]}}
    match=re.fullmatch(r'(?:acrescente|adicione) "([^"]+)" (?:ao|no) arquivo "([^"]+)"',text,re.I)
    if match:return {'tool':'files.append_text','args':{'path':match[2],'text':match[1]}}
    match=re.fullmatch(r'(?:leia|ler) (?:o )?arquivo "([^"]+)"',text,re.I)
    if match:return {'tool':'files.read_text','args':{'path':match[1]}}
    match=re.fullmatch(r'crie (?:o )?arquivo "([^"]+)" com (?:o )?texto "([^"]*)"',text,re.I)
    if match:return {'tool':'files.create_text','args':{'path':match[1],'text':match[2]}}
    match=re.fullmatch(r'substitua "([^"]+)" por "([^"]*)" no arquivo "([^"]+)"',text,re.I)
    if match:return {'tool':'files.replace_text','args':{'path':match[3],'old':match[1],'text':match[2]}}
    return {'gap':('file_workflow' if any(w in lower for w in ('arquivo','pasta','documento')) else 'command_unrecognized'),'reply':'Estou sem geração do Gemini. Tente um comando direto, como “pesquise sobre astronomia”, “me lembre em cinco minutos de beber água” ou “abra a calculadora”. Não executei nenhuma ação para este pedido.'}
