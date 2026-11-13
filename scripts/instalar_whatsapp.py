"""Instala o serviço local do WhatsApp da Viv (GoWA, go-whatsapp-web-multidevice).

Baixa a mesma versão que o Kardap.IA usa, confere o SHA-256 publicado no release e
extrai o executável em bin/gowa/. Não acessa o .env nem o WhatsApp.

Uso: .venv\\Scripts\\python.exe scripts\\instalar_whatsapp.py
"""
import hashlib
import io
import sys
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
VERSION = "9.6.0"
ASSET = f"whatsapp_{VERSION}_windows_amd64.zip"
URL = f"https://github.com/aldinokemal/go-whatsapp-web-multidevice/releases/download/v{VERSION}/{ASSET}"
SHA256 = "9db29f358b63dbc959b774ff0423c6547390ade3591aedbf4477ea7e8dfdba5e"
TARGET = ROOT / "bin" / "gowa" / "windows-amd64.exe"


def main() -> int:
    if TARGET.is_file():
        print(f"Já instalado em {TARGET}.")
        return 0
    print(f"Baixando o GoWA {VERSION}…")
    with httpx.Client(follow_redirects=True, timeout=180) as http:
        response = http.get(URL)
        response.raise_for_status()
    digest = hashlib.sha256(response.content).hexdigest()
    if digest != SHA256:
        print(f"Arquivo recusado: o SHA-256 não confere ({digest}). Nada foi instalado.", file=sys.stderr)
        return 1
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        name = next((n for n in archive.namelist() if n.endswith("windows-amd64.exe")), None)
        if name is None:
            print("O pacote não tem o executável esperado. Nada foi instalado.", file=sys.stderr)
            return 1
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_bytes(archive.read(name))
    print(f"Instalado em {TARGET}. Abra a Viv e diga “Viv, conecta meu WhatsApp”.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
