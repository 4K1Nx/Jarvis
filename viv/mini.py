"""Modo miniatura: com a janela da Viv minimizada, só o avatar fica num canto da tela.

A janela principal é uma janela de app do Edge. Enquanto ela está minimizada, este módulo mantém aberta uma
janelinha sem moldura, sempre por cima, com a página /mini (o mesmo avatar da HUD, maior): ele reage, mexe a
boca e mostra o humor ali. Restaurar a janela principal fecha a miniatura; clicar na miniatura restaura a
janela principal. O canto e o próprio modo são ajustes ("miniatura.canto", "miniatura.ativa"); o tamanho e a
opacidade do avatar também ("avatar.tamanho", "avatar.opacidade"), os mesmos do avatar da janela principal.

A janelinha roda em outro processo (`python -m viv.mini URL CANTO TAMANHO OPACIDADE`), porque o pywebview precisa
da thread principal, que aqui é do servidor. Ela não aparece na barra de tarefas nem no Alt+Tab: é parte da Viv,
não um app à parte.
"""
import atexit
import subprocess
import sys
import threading
import unicodedata

TITLE = "Viv"                      # título da janela principal (web/index.html)
SIZE = (200, 156)                  # largura e altura pedidas ao abrir a janelinha
VISIBLE = (200, 118)               # o que aparece de fato: sem moldura, a janela sai mais baixa que o pedido
MARGIN = 18
CORNERS = ("inferior direito", "inferior esquerdo", "superior direito", "superior esquerdo")
SW_RESTORE = 9
MINI_TITLE = "Viv mini"
NOTICES_TITLE = "Viv avisos"
NOTICES_WIDTH = 340                # largura da janelinha de avisos (px de tela, antes da escala do Windows)


def look_of(settings) -> tuple[int, int]:
    """(tamanho, opacidade) do avatar em %, dentro dos limites das configurações."""
    def pct(key, low, high, default):
        try:
            return max(low, min(high, int(settings.get(key))))
        except (TypeError, ValueError):
            return default
    return pct("avatar.tamanho", 50, 300, 100), pct("avatar.opacidade", 20, 100, 100)


def scaled(size: tuple, percent: int) -> tuple[int, int]:
    return round(size[0] * percent / 100), round(size[1] * percent / 100)


def corner_of(text) -> str:
    """Canto escolhido nas configurações; texto livre ("embaixo à esquerda") também serve."""
    folded = "".join(c for c in unicodedata.normalize("NFKD", str(text or "").casefold()) if not unicodedata.combining(c))
    top = any(word in folded for word in ("superior", "cima", "topo", "alto"))
    left = "esquerd" in folded
    return f"{'superior' if top else 'inferior'} {'esquerdo' if left else 'direito'}"


def position(corner: str, area: tuple, size: tuple = VISIBLE, margin: int = MARGIN) -> tuple[int, int]:
    """Canto superior esquerdo da miniatura dentro da área útil da tela (esquerda, topo, direita, base)."""
    left, top, right, bottom = area
    corner = corner_of(corner)
    x = left + margin if corner.endswith("esquerdo") else right - size[0] - margin
    y = top + margin if corner.startswith("superior") else bottom - size[1] - margin
    return int(x), int(y)


# ---- Windows -------------------------------------------------------------------------------------
def _hud_window() -> int:
    import ctypes
    from ctypes import wintypes
    user = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(handle, _):
        if user.IsWindowVisible(handle):
            title, kind = ctypes.create_unicode_buffer(64), ctypes.create_unicode_buffer(64)
            user.GetWindowTextW(handle, title, 64)
            user.GetClassNameW(handle, kind, 64)
            if title.value == TITLE and kind.value.startswith("Chrome_WidgetWin"):
                found.append(handle)
                return False
        return True
    user.EnumWindows(each, 0)
    return found[0] if found else 0


def hud_state() -> str:
    """"minimizada", "aberta" ou "fechada"."""
    if sys.platform != "win32":
        return "fechada"
    import ctypes
    handle = _hud_window()
    if not handle:
        return "fechada"
    return "minimizada" if ctypes.windll.user32.IsIconic(handle) else "aberta"


def restore_hud() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    handle = _hud_window()
    if not handle:
        return False
    ctypes.windll.user32.ShowWindow(handle, SW_RESTORE)
    ctypes.windll.user32.SetForegroundWindow(handle)
    return True


def work_area() -> tuple:
    import ctypes
    from ctypes import wintypes
    rect = wintypes.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0)      # SPI_GETWORKAREA: sem a barra de tarefas
    return rect.left, rect.top, rect.right, rect.bottom


def _spawn(url: str, corner: str, look: tuple = (100, 100)):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen([sys.executable, "-m", "viv.mini", url, corner, str(look[0]), str(look[1])], creationflags=flags,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _kill_tree(proc) -> None:
    """Encerra a janelinha. O python do .venv é um lançador: a janela é de um processo filho, que fecha junto."""
    try:
        import psutil
        family = psutil.Process(proc.pid).children(recursive=True)
    except Exception:
        family = []
    for member in family + [proc]:
        try:
            member.terminate()
        except Exception:
            pass


class Mini:
    """Abre a miniatura enquanto a janela principal está minimizada e a fecha quando ela volta."""

    def __init__(self, settings, url: str, state=hud_state, spawn=_spawn, restore=restore_hud, poll: float = 0.6, kill=None):
        self.settings, self.url = settings, url
        self._state, self._spawn, self._restore, self.poll = state, spawn, restore, poll
        self._kill = kill or _kill_tree
        self._proc, self._shown = None, None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def tick(self) -> None:
        shown = (corner_of(self.settings.get("miniatura.canto")), look_of(self.settings))
        wanted = bool(self.settings.get("miniatura.ativa")) and self._state() == "minimizada"
        with self._lock:
            running = self._proc is not None and self._proc.poll() is None
            if running and (not wanted or shown != self._shown):     # canto, tamanho ou opacidade novos: reabre
                self._close()
                running = False
            if wanted and not running:
                self._proc, self._shown = self._spawn(self.url, *shown), shown

    def _close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            self._kill(proc)

    def restore(self) -> bool:
        """Clique na miniatura: a janela principal volta (e a miniatura some no próximo ciclo)."""
        return bool(self._restore())

    def start(self) -> None:
        def loop():
            while not self._stop.wait(self.poll):
                try:
                    self.tick()
                except Exception:
                    pass                  # a miniatura é um enfeite: nunca derruba a Viv
        atexit.register(self.stop)
        threading.Thread(target=loop, daemon=True, name="viv-miniatura").start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            self._close()


def _find(title: str, tries: int = 50) -> int:
    import ctypes
    import time
    for _ in range(tries):                                # a janela leva um instante para existir
        handle = ctypes.windll.user32.FindWindowW(None, title)
        if handle:
            return handle
        time.sleep(0.1)
    return 0


def _style(handle: int, alpha: int, show: bool) -> None:
    """Tira a janela da barra de tarefas e do Alt+Tab, aplica a opacidade e arredonda os cantos (Windows 11)."""
    import ctypes
    user = ctypes.windll.user32
    user.GetWindowLongW.restype = ctypes.c_long
    GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW, WS_EX_LAYERED, LWA_ALPHA = -20, 0x80, 0x40000, 0x80000, 0x2
    style = user.GetWindowLongW(handle, GWL_EXSTYLE)
    user.ShowWindow(handle, 0)                            # a barra de tarefas só esquece a janela se ela sumir e voltar
    user.SetWindowLongW(handle, GWL_EXSTYLE, (style | WS_EX_TOOLWINDOW | WS_EX_LAYERED) & ~WS_EX_APPWINDOW)
    user.SetLayeredWindowAttributes(handle, 0, round(255 * alpha / 100), LWA_ALPHA)
    try:
        corner = ctypes.c_int(2)                          # DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(handle, 33, ctypes.byref(corner), ctypes.sizeof(corner))
    except Exception:
        pass
    if show:
        user.ShowWindow(handle, 4)                        # SW_SHOWNOACTIVATE: não rouba o foco


def _handle(window, title: str) -> int:
    """HWND da janela do pywebview. Pelo título não dá: o pywebview cria mais de uma janela com o mesmo nome."""
    import time
    for _ in range(50):
        native = getattr(window, "native", None)
        if native is not None:
            try:
                return int(native.Handle.ToInt64())
            except Exception:
                break
        time.sleep(0.1)
    return _find(title)


BACKGROUND = "#0c0916"              # fundo das janelinhas: o padrão do pywebview é branco e a transparência não pega


def _loaded(window, check: str) -> bool:
    try:
        return bool(window.evaluate_js(check))
    except Exception:
        return False


def _keep_loaded(window, url: str, check: str, tries: int = 6) -> None:
    """A página às vezes não carrega (a Viv ainda subindo, rede local engasgada) e a janela fica vazia: recarrega."""
    import time
    for _ in range(tries):
        time.sleep(4)
        if _loaded(window, check):
            return
        try:
            window.load_url(url)
        except Exception:
            return


def _blend_in(alpha: int, mini_window=None, notices_window=None, notices=None, url: str = "") -> None:
    import threading
    handle = _handle(mini_window, MINI_TITLE)
    if handle:
        _style(handle, alpha, True)
    if notices_window is not None:
        handle = _handle(notices_window, NOTICES_TITLE)
        if handle:
            _style(handle, alpha, False)
        notices.fit(0)                                    # escondida até chegar um aviso
    if url and mini_window is not None:
        threading.Thread(target=_keep_loaded, args=(mini_window, url, "!!window.VivMini"), daemon=True).start()
    if mini_window is not None:
        threading.Thread(target=_follow_cursor, args=(mini_window, MINI_TITLE), daemon=True).start()
    if url and notices_window is not None:
        threading.Thread(target=_keep_loaded, args=(notices_window, _notices_url(url), "!!window.VivAvisos"),
                         daemon=True).start()


def gaze(cursor: tuple, rect: tuple) -> tuple[float, float]:
    """Direção do cursor vista do centro da janelinha, de −1 a 1 (a uns 700 px ela olha no limite)."""
    left, top, right, bottom = rect
    dx, dy = (cursor[0] - (left + right) / 2) / 700, (cursor[1] - (top + bottom) / 2) / 500
    far = max(1.0, (dx * dx + dy * dy) ** .5)
    return round(dx / far * 1.2, 3), round(dy / far, 3)


def _follow_cursor(window, title: str, every: float = 0.05) -> None:
    """Os olhos da miniatura seguem o mouse pela tela toda: a página só veria o mouse em cima dela."""
    import ctypes
    import time
    from ctypes import wintypes
    user = ctypes.windll.user32
    handle = _handle(window, title)
    last = None
    while handle:
        point, rect = wintypes.POINT(), wintypes.RECT()
        if user.GetCursorPos(ctypes.byref(point)) and user.GetWindowRect(handle, ctypes.byref(rect)):
            cursor = (point.x, point.y)
            if cursor != last:                            # só quando o mouse se mexe: parado, ela volta a olhar à toa
                last = cursor
                dx, dy = gaze(cursor, (rect.left, rect.top, rect.right, rect.bottom))
                try:
                    window.evaluate_js(f"window.VivAvatar && window.VivAvatar.lookAt({dx}, {dy})")
                except Exception:
                    return                                # a janela fechou
        time.sleep(every)


def _notices_url(url: str) -> str:
    return url.rsplit("/mini", 1)[0] + "/avisos"


class Notices:
    """API da página /avisos: a janelinha cresce até caber nos avisos, fica no canto superior direito e some
    quando eles acabam. Usa os próprios métodos do pywebview, que mexem na janela pela thread dela."""

    _window = None                                        # preenchido em main(); privado: o pywebview não expõe ao JS

    def fit(self, height, scale=1) -> bool:
        window = self._window
        if window is None:
            return False
        height = max(0, int(height))
        if height <= 0:
            window.hide()
            return True
        left, top, right, _ = work_area()
        window.resize(NOTICES_WIDTH, height)
        window.move(right - NOTICES_WIDTH - MARGIN, top + MARGIN)
        window.show()
        return True


def main(argv: list[str]) -> int:
    url, corner = argv[0], argv[1] if len(argv) > 1 else CORNERS[0]
    size, alpha = (int(argv[2]) if len(argv) > 2 else 100), (int(argv[3]) if len(argv) > 3 else 100)
    import webview
    x, y = position(corner, work_area(), scaled(VISIBLE, size))
    width, height = scaled(SIZE, size)
    mini_window = webview.create_window(MINI_TITLE, url, width=width, height=height, x=x, y=y, frameless=True, on_top=True,
                                        easy_drag=True, resizable=False, shadow=False, focus=False, min_size=(40, 30),
                                        background_color=BACKGROUND)
    area, notices = work_area(), Notices()
    notices._window = notices_window = webview.create_window(
        NOTICES_TITLE, _notices_url(url), js_api=notices, width=NOTICES_WIDTH, height=60,
        x=area[2] - NOTICES_WIDTH - MARGIN, y=area[1] + MARGIN, frameless=True, on_top=True, easy_drag=False,
        resizable=True, shadow=False, focus=False, min_size=(40, 10), background_color=BACKGROUND)
    webview.start(_blend_in, (alpha, mini_window, notices_window, notices, url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
