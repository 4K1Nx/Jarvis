"""Bounded UTF-8 operations for explicit, owner-confirmed requests."""
from pathlib import Path
import uuid


def target_path(path):
    target = Path(path).expanduser()
    if not target.is_absolute():
        raise ValueError('Informe o caminho absoluto do arquivo.')
    if any(part.startswith('.') for part in target.parts):
        raise ValueError('Este comando aceita apenas arquivos .txt ou .md fora de pastas ocultas.')
    target = target.resolve()
    if target.suffix.casefold() not in ('.txt', '.md') or any(part.startswith('.') for part in target.parts):
        raise ValueError('Este comando aceita apenas arquivos .txt ou .md fora de pastas ocultas.')
    if not target.parent.is_dir():
        raise ValueError('A pasta informada não existe.')
    if target.exists() and target.stat().st_size > 2_000_000:
        raise ValueError('Arquivo grande demais para esta edição simples.')
    return target


def operate(path, mode, text='', old=''):
    try:
        target = target_path(path)
        if len(text.encode('utf-8')) > 100_000:
            return 'Não foi possível editar: texto grande demais.'
        if mode == 'read':
            content = target.read_text(encoding='utf-8')
            return (content[:6000] or 'Arquivo vazio.') + ('\n[Leitura limitada a 6000 caracteres.]' if len(content)>6000 else '')
        if mode == 'create':
            with target.open('x', encoding='utf-8') as stream:
                stream.write(text)
            return 'Arquivo criado sem sobrescrever outro arquivo.'
        if mode == 'append':
            if target.exists():
                target.read_text(encoding='utf-8')
            with target.open('a', encoding='utf-8') as stream:
                stream.write('\n'+text+'\n')
            return 'Texto acrescentado ao arquivo. O conteúdo anterior foi preservado.'
        if mode != 'replace':
            raise ValueError('Operação inválida.')
        original = target.read_bytes()
        content = original.decode('utf-8')
        if not old or content.count(old) != 1:
            return 'Não foi possível substituir: o trecho deve aparecer exatamente uma vez.'
        updated = content.replace(old, text, 1).encode('utf-8')
        backup = target.with_name(target.name+'.viv-backup-'+uuid.uuid4().hex)
        # Exclusive backup; refuse to overwrite a file changed since the read.
        with backup.open('xb') as stream:
            stream.write(original)
        with target.open('r+b') as stream:
            if stream.read() != original:
                return 'Não foi possível substituir: o arquivo mudou durante a operação. Backup preservado.'
            stream.seek(0)
            stream.write(updated)
            stream.truncate()
        return 'Trecho substituído. Cópia de segurança preservada ao lado do arquivo.'
    except ValueError as exc:
        return 'Não foi possível: '+str(exc)
    except (OSError, UnicodeError):
        return 'Não foi possível acessar ou editar o arquivo; verifique existência, UTF-8 e permissões. Nenhum arquivo existente é sobrescrito pela criação.'


def append_text(path, text):
    return operate(path, 'append', text)
