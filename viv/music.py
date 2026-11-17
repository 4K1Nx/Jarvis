"""Música: controla o Spotify do PC e faz o avatar dançar com o que está tocando.

Controle sem conta nem chave: os comandos de mídia (tocar/pausar, próxima, anterior) vão direto para a janela
do Spotify como WM_APPCOMMAND, então não mexem num vídeo aberto no navegador. A música atual vem do título da
janela ("Artista - Faixa"; pausado, o título é só "Spotify..."). O volume do Spotify é o do mixer do Windows,
separado do volume geral.

Visualizador: com o Spotify tocando e o ajuste "musica.visualizar" ligado, o som que sai do PC é capturado em
loopback (pacote soundcard), dividido em 10 bandas do grave ao agudo e publicado no barramento ("music"), 20
vezes por segundo, para o avatar da HUD e da miniatura. Nada é gravado nem enviado para fora.
"""
import os
import random
import re
import subprocess
import threading
import time
import warnings

import numpy as np

from viv.bus import BUS

PROCESS = "spotify.exe"
WM_APPCOMMAND = 0x319
COMMANDS = {"tocar_pausar": 14, "proxima": 11, "anterior": 12, "parar": 13}
MEDIA_KEYS = {"tocar_pausar": 0xB3, "proxima": 0xB0, "anterior": 0xB1, "parar": 0xB2}
RATE, BLOCK, FFT = 48000, 1024, 2048
EDGES = np.geomspace(40, 16000, 11)            # 10 bandas em escala logarítmica, como o ouvido
FPS = 20


# ---- Spotify -------------------------------------------------------------------------------------
def _windows() -> list[tuple[int, str]]:
    """Janelas do Spotify com título: (handle, título)."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes
    import psutil
    user = ctypes.windll.user32
    pids = {p.pid for p in psutil.process_iter(["name"]) if (p.info.get("name") or "").lower() == PROCESS}
    if not pids:
        return []
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(handle, _):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        if pid.value in pids:
            title = ctypes.create_unicode_buffer(256)
            user.GetWindowTextW(handle, title, 256)
            if title.value.strip() and title.value not in ("Default IME", "MSCTFIME UI") and not title.value.startswith("GDI+"):
                found.append((handle, title.value.strip()))
        return True
    user.EnumWindows(each, 0)
    return found


def parse_title(title: str) -> dict | None:
    """"Artista - Faixa" -> {"artista", "faixa"}; título de pausa ("Spotify Premium") -> None."""
    title = (title or "").strip()
    if not title or title.lower().startswith("spotify") or " - " not in title:
        return None
    artist, track = title.split(" - ", 1)
    return {"artista": artist.strip(), "faixa": track.strip()}


def now_playing() -> dict | None:
    for _, title in _windows():
        song = parse_title(title)
        if song:
            return song
    return None


def running() -> bool:
    return bool(_windows())


def command(action: str) -> bool:
    """Manda o comando para a janela do Spotify; sem ela, usa a tecla de mídia do Windows."""
    if action not in COMMANDS:
        raise ValueError(f"comando desconhecido: {action}. Use: {', '.join(COMMANDS)}")
    if os.name != "nt":
        return False
    import ctypes
    user = ctypes.windll.user32
    windows = _windows()
    if windows:
        handle = windows[0][0]
        user.SendMessageW(handle, WM_APPCOMMAND, handle, COMMANDS[action] << 16)
        return True
    key = MEDIA_KEYS[action]
    user.keybd_event(key, 0, 0, 0)
    user.keybd_event(key, 0, 2, 0)                # KEYEVENTF_KEYUP
    return False


def open_app() -> None:
    os.startfile("spotify:") if os.name == "nt" else subprocess.Popen(["spotify"])


def _session():
    from pycaw.pycaw import AudioUtilities
    for session in AudioUtilities.GetAllSessions():
        if session.Process is not None and session.Process.name().lower() == PROCESS:
            return session
    return None


def set_volume(percent: int) -> int:
    """Volume do Spotify no mixer do Windows (0 a 100), sem mexer no volume geral."""
    level = max(0, min(100, int(percent)))
    session = _session()
    if session is None:
        raise RuntimeError("o Spotify não está tocando som agora; abra-o e dê play primeiro")
    session.SimpleAudioVolume.SetMasterVolume(level / 100.0, None)
    return level


def get_volume() -> int | None:
    session = _session()
    return None if session is None else round(session.SimpleAudioVolume.GetMasterVolume() * 100)


# ---- tocar algo específico -----------------------------------------------------------------------
# Sem conta de desenvolvedor: o ID do Spotify vem de uma busca na web (links open.spotify.com) e o app toca ao
# abrir "spotify:track:ID". Artista, álbum e playlist tocam a partir de uma faixa deles, com o resto na fila
# ("?context="); as faixas vêm da página pública de incorporação do Spotify.
KINDS = {"musica": "track", "artista": "artist", "album": "album", "playlist": "playlist"}
EXTRAS = ("ao vivo", "live", "remix", "karaoke", "cover", "instrumental", "sped up", "slowed", "acustic", "acoustic")


def _plain(text) -> str:
    import unicodedata
    text = unicodedata.normalize("NFKD", str(text or "").casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


def score(query: str, title: str) -> float:
    """Quanto o título do resultado bate com o pedido: palavras do pedido presentes, menos versões que não
    foram pedidas (ao vivo, remix...)."""
    words = [w for w in re.findall(r"\w+", _plain(query)) if len(w) > 1]
    plain = _plain(title)
    hit = sum(w in plain for w in words) / max(1, len(words))
    extra = sum(e in plain.split("|")[0] and e not in _plain(query) for e in EXTRAS)
    return hit - 0.3 * extra


def find(query: str, kind: str, search, limit: int = 4) -> list[dict]:
    """Links do Spotify para o pedido, do melhor para o pior: [{"id", "titulo"}]. `search(texto)` -> [{"title", "url"}]."""
    pattern = re.compile(rf"open\.spotify\.com/(?:intl-[\w-]+/)?{kind}/([A-Za-z0-9]{{22}})")
    ranked, seen = [], set()
    for text in (f"open.spotify.com {kind} {query}", f"{query} spotify {kind}", f"{query} spotify"):
        try:
            hits = search(text)
        except Exception:
            continue
        for rank, hit in enumerate(hits):
            found = pattern.search(hit.get("url", ""))
            if not found or found.group(1) in seen:
                continue
            seen.add(found.group(1))
            ranked.append((score(query, hit.get("title", "")) - rank * 0.01 - len(ranked) * 0.001,
                           {"id": found.group(1), "titulo": hit.get("title", "").split("|")[0].strip()}))
        if any(value >= 0.99 for value, _ in ranked):
            break
    ranked.sort(key=lambda item: -item[0])
    return [item for value, item in ranked if value > 0.3][:limit]


def matches(song: dict | None, title: str) -> bool:
    """A faixa que começou a tocar é a pedida? Compara o nome da faixa com o título do resultado."""
    if not song:
        return False
    name = _plain(re.split(r" - (?:song|música|musica|canción)", title or "", maxsplit=1)[0])
    track = _plain(song.get("faixa", ""))
    return bool(name) and (name in track or track in name)


def tracks_of(kind: str, ident: str, get=None) -> list[dict]:
    """Faixas de um artista, álbum ou playlist pela página pública de incorporação: [{"id", "faixa", "artista"}]."""
    import json
    if get is None:
        import httpx
        get = lambda url: httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15, follow_redirects=True).text
    page = get(f"https://open.spotify.com/embed/{kind}/{ident}")
    found = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', page, re.S)
    rows = []
    if found:
        def walk(node):
            if isinstance(node, dict):
                if isinstance(node.get("trackList"), list):
                    rows.extend(node["trackList"])
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        try:
            walk(json.loads(found.group(1)))
        except ValueError:
            pass
    tracks = [{"id": row["uri"].rsplit(":", 1)[-1], "faixa": row.get("title", ""), "artista": row.get("subtitle", "")}
              for row in rows if str(row.get("uri", "")).startswith("spotify:track:") and row.get("isPlayable", True)]
    if not tracks:                                 # formato mudou: ao menos os IDs
        ids = dict.fromkeys(re.findall(r"spotify:track:([A-Za-z0-9]{22})", page))
        tracks = [{"id": i, "faixa": "", "artista": ""} for i in ids]
    return tracks


def uri_for(kind: str, ident: str, tracks: list[dict], shuffle: bool = False) -> str:
    if kind == "track":
        return f"spotify:track:{ident}"
    if not tracks:
        raise LookupError("não achei faixas tocáveis aí")
    first = random.choice(tracks) if shuffle else tracks[0]
    return f"spotify:track:{first['id']}?context=spotify:{kind}:{ident}"


def play_uri(uri: str, wait=time.sleep) -> dict | None:
    """Abre o link no Spotify (que começa a tocar) e devolve o que passou a tocar."""
    if not running():
        open_app()
        for _ in range(20):
            wait(0.5)
            if running():
                break
        wait(2.0)                                  # o app recém-aberto ainda carrega a conta
    before = now_playing()
    if before:                                     # tocando, o link só abre a página: pausa antes
        command("tocar_pausar")
        wait(0.8)
    os.startfile(uri)
    song = None
    for _ in range(16):                            # até 8 s para trocar de faixa
        wait(0.5)
        song = now_playing()
        if song and song != before:
            return song
    return song


# ---- visualizador --------------------------------------------------------------------------------
def analyze(samples: np.ndarray, peaks: np.ndarray, dt: float, rate: int = RATE) -> tuple[list[float], float, float]:
    """Bloco de áudio (mono) -> (10 bandas 0..1, grave 0..1, volume 0..1). `peaks` é o ganho automático de cada
    banda (atualizado aqui): uma música baixa enche as barras tanto quanto uma alta."""
    if samples.size < 64:
        return [0.0] * 10, 0.0, 0.0
    window = samples[-FFT:] * np.hanning(min(FFT, samples.size))
    spectrum = np.abs(np.fft.rfft(window, n=FFT))
    freqs = np.fft.rfftfreq(FFT, 1 / rate)
    energy = np.array([spectrum[(freqs >= lo) & (freqs < hi)].mean() if ((freqs >= lo) & (freqs < hi)).any() else 0.0
                       for lo, hi in zip(EDGES[:-1], EDGES[1:])])
    decay = 0.5 ** (dt / 3.0)                    # o pico de cada banda cai pela metade a cada 3 s
    np.maximum(energy, peaks * decay, out=peaks)
    np.maximum(peaks, 1e-3, out=peaks)
    bands = np.clip(energy / peaks, 0, 1) ** 1.4  # contraste: as batidas se destacam
    level = float(min(1.0, np.sqrt(np.mean(samples ** 2)) * 4))
    if level < 0.004:                            # silêncio de verdade: barras apagadas
        bands[:] = 0
    return [round(float(b), 3) for b in bands], round(float(bands[:2].max()), 3), round(level, 3)


def cover(song: dict, get=None) -> str:
    """Capa do álbum da faixa (busca pública do iTunes, sem chave), em 300x300; vazio se não achar."""
    import json
    if get is None:
        import httpx
        get = lambda url, params: httpx.get(url, params=params, timeout=6).text
    try:
        data = json.loads(get("https://itunes.apple.com/search",
                              {"term": f"{song['artista']} {song['faixa']}", "entity": "song", "limit": 5}))
    except Exception:
        return ""
    results = data.get("results") or []
    wanted = _plain(song["faixa"]).split(" (")[0].split(" - ")[0]
    best = next((r for r in results if wanted and wanted in _plain(r.get("trackName", ""))), results[0] if results else None)
    art = str((best or {}).get("artworkUrl100") or "")
    return art.replace("100x100bb", "300x300bb") if art.startswith("https://") else ""


class Visualizer:
    """Acompanha o Spotify: avisa a música que começou (com a capa do álbum) e, enquanto toca, publica as bandas
    do som do PC para o avatar."""

    def __init__(self, settings, playing=now_playing, poll: float = 1.0, find_cover=cover):
        self.settings, self._playing, self.poll, self._cover = settings, playing, poll, find_cover
        self._stop = threading.Event()
        self._thread = None
        self._last = None                        # última faixa avisada

    def _now(self) -> dict | None:
        try:
            return self._playing()
        except Exception:
            return None

    def _on(self, key: str) -> bool:
        try:
            return bool(self.settings.get(key))
        except Exception:
            return False

    def wanted(self) -> dict | None:
        return self._now() if self._on("musica.visualizar") else None

    def announce(self, song: dict | None) -> None:
        """Faixa nova (não a mesma voltando da pausa): aviso na tela com a capa, buscada fora deste laço."""
        if not song or song == self._last:
            return
        self._last = song
        if not self._on("musica.avisar"):
            return

        def send():
            BUS.emit("card", song["faixa"], kind="music", ok=True, body=song["artista"], image=self._cover(song))
        threading.Thread(target=send, daemon=True, name="viv-musica-capa").start()

    def _stream(self, song: dict) -> None:
        import soundcard as sc
        speaker = sc.default_speaker()
        mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
        peaks = np.full(10, 1e-3)
        buffer = np.zeros(0, dtype=np.float32)
        checked = last = time.monotonic()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")      # "data discontinuity" do loopback não importa aqui
            with mic.recorder(samplerate=RATE, channels=2, blocksize=BLOCK) as recorder:
                while not self._stop.is_set():
                    chunk = recorder.record(numframes=RATE // FPS)
                    buffer = np.concatenate([buffer, chunk.mean(axis=1)])[-FFT:]
                    now = time.monotonic()
                    bands, bass, level = analyze(buffer, peaks, now - last)
                    last = now
                    BUS.emit("music", playing=True, bands=bands, bass=bass, level=level,
                             track=f"{song['artista']} - {song['faixa']}")
                    if now - checked >= self.poll:           # pausou, trocou de faixa ou desligou o ajuste?
                        checked = now
                        song = self.wanted()
                        self.announce(song)
                        if not song:
                            return

    def _loop(self) -> None:
        while not self._stop.wait(self.poll):
            song = self._now()
            self.announce(song)
            if not song or not self._on("musica.visualizar"):
                continue
            try:
                self._stream(song)
            except Exception:
                self._stop.wait(5)               # sem dispositivo de saída ou troca de fone: tenta de novo depois
            BUS.emit("music", playing=False)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="viv-musica")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
