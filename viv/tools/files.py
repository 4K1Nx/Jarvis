"""Arquivos e pastas do usuário.

Todo caminho passa por `_paths.resolve`: "Desktop", "Área de Trabalho" e "Downloads" apontam
para as pastas reais do Windows, mesmo quando o OneDrive as mudou de lugar.
"""
import glob
import os
import shutil
import subprocess

from viv.tools import _text_files
from viv.tools._paths import personal_roots, resolve
from viv.tools.registry import tool


@tool("files_find", "Procurar arquivos pelo nome nas pastas pessoais (Área de Trabalho, Documentos, Downloads, Imagens).",
      {"query": {"type": "string"}, "root": {"type": "string", "required": False}}, title="Procurando arquivo")
def find(query, root=None, ctx=None):
    roots = [resolve(root)] if root else personal_roots()
    hits = []
    for folder in roots:
        if not os.path.isdir(folder):
            continue
        for path in glob.iglob(os.path.join(folder, "**", f"*{glob.escape(query)}*"), recursive=True):
            hits.append(path)
            if len(hits) >= 20:
                return "\n".join(hits)
    return "\n".join(hits) or f"nada encontrado com '{query}'"


@tool("files_open", "Abrir um arquivo ou pasta no aplicativo padrão.", {"path": {"type": "string"}}, title="Abrindo")
def open_path(path, ctx=None):
    path = str(resolve(path))
    if os.name == "nt":
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", path])
    return f"{path} aberto"


@tool("files_recent", "Listar os arquivos modificados mais recentemente numa pasta (padrão: Downloads).",
      {"folder": {"type": "string", "required": False}, "count": {"type": "integer", "required": False}},
      title="Arquivos recentes")
def recent(folder=None, count=10, ctx=None):
    folder = str(resolve(folder or "Downloads"))
    items = sorted(((os.path.getmtime(os.path.join(folder, f)), f) for f in os.listdir(folder)), reverse=True)
    return "\n".join(f for _, f in items[:int(count)]) or "pasta vazia"


@tool("files_read_text", "Ler até 6000 caracteres de um arquivo .txt ou .md.",
      {"path": {"type": "string"}}, title="Lendo arquivo")
def read_text(path, ctx=None):
    return _text_files.operate(resolve(path), "read")


@tool("files_create_text", "Criar um arquivo .txt ou .md novo, sem sobrescrever. Aceita 'Desktop/nome.txt' ou caminho absoluto.",
      {"path": {"type": "string"}, "text": {"type": "string"}}, title="Criando arquivo")
def create_text(path, text, ctx=None):
    return _text_files.operate(resolve(path), "create", text)


@tool("files_append_text", "Acrescentar texto ao fim de um arquivo .txt ou .md. Exige confirmação.",
      {"path": {"type": "string"}, "text": {"type": "string"}}, dangerous=True, title="Acrescentar texto")
def append_text(path, text, ctx=None):
    return _text_files.operate(resolve(path), "append", text)


@tool("files_replace_text", "Substituir um trecho exato e único em .txt ou .md, com backup. Exige confirmação.",
      {"path": {"type": "string"}, "old": {"type": "string"}, "text": {"type": "string"}},
      dangerous=True, title="Substituir texto")
def replace_text(path, old, text, ctx=None):
    return _text_files.operate(resolve(path), "replace", text, old)


def _existing(path) -> str:
    source = resolve(path)
    if not source.exists():
        raise FileNotFoundError(f"não encontrei {source}. Use files_find para achar o caminho certo.")
    return str(source)


def _destination(source: str, dst) -> str:
    """Destino que é uma pasta existente recebe o arquivo com o mesmo nome; nada é sobrescrito."""
    target = resolve(dst)
    if target.is_dir():
        target = target / os.path.basename(source)
    if target.exists():
        raise FileExistsError(f"já existe {target}; escolha outro nome")
    if not target.parent.is_dir():
        raise FileNotFoundError(f"a pasta {target.parent} não existe; crie com fs_mkdir")
    return str(target)


@tool("files_move", "Mover ou renomear um arquivo ou pasta. Exige confirmação.",
      {"src": {"type": "string"}, "dst": {"type": "string"}}, dangerous=True, title="Mover arquivo")
def move(src, dst, ctx=None):
    source = _existing(src)
    target = _destination(source, dst)
    shutil.move(source, target)
    return f"movido para {target}"


@tool("fs_copy", "Copiar um arquivo ou pasta para outro lugar, sem sobrescrever nada.",
      {"src": {"type": "string"}, "dst": {"type": "string"}}, title="Copiando")
def fs_copy(src, dst, ctx=None):
    source = _existing(src)
    target = _destination(source, dst)
    shutil.copytree(source, target) if os.path.isdir(source) else shutil.copy2(source, target)
    return f"copiado para {target}"


@tool("fs_mkdir", "Criar uma pasta (e as pastas acima dela, se faltarem).", {"path": {"type": "string"}}, title="Criando pasta")
def fs_mkdir(path, ctx=None):
    target = resolve(path)
    target.mkdir(parents=True, exist_ok=True)
    return f"pasta pronta: {target}"


@tool("fs_list", "Listar o conteúdo de uma pasta.", {"path": {"type": "string"}}, title="Listando pasta")
def fs_list(path, ctx=None):
    return "\n".join(sorted(os.listdir(resolve(path)))[:200]) or "pasta vazia"


@tool("fs_read", "Ler um arquivo de texto UTF-8 qualquer (até 8000 caracteres). Para PDF, Word, PowerPoint e Excel use documento_ler.",
      {"path": {"type": "string"}}, title="Lendo arquivo")
def fs_read(path, ctx=None):
    with open(resolve(path), encoding="utf-8", errors="ignore") as stream:
        return stream.read(8000)


@tool("fs_write", "Gravar um arquivo de texto, sobrescrevendo se existir. Exige confirmação.",
      {"path": {"type": "string"}, "content": {"type": "string"}}, dangerous=True, title="Gravar arquivo")
def fs_write(path, content, ctx=None):
    path = str(resolve(path))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(content)
    return f"gravado {path}"


@tool("fs_delete", "Apagar um arquivo ou pasta. Irreversível; exige confirmação.",
      {"path": {"type": "string"}}, dangerous=True, title="Apagar")
def fs_delete(path, ctx=None):
    path = _existing(path)
    shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    return f"apagado {path}"
