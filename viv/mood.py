"""Humor da Viv.

Dois eixos, de -1 a 1: afeto (como ela se sente em relação à conversa) e energia.
O que acontece mexe nos eixos — um elogio, uma grosseria, uma ferramenta que falha,
a madrugada — e os dois voltam devagar ao ponto de repouso. Do par sai um humor com
nome, que muda as cores da HUD, a expressão da fala e o jeito de responder.

Humores negativos podem recusar um pedido uma vez. A recusa nunca atinge os ajustes,
a memória, os lembretes nem o próprio sono, e depois dela tudo é atendido por alguns
minutos: insistir sempre funciona. Desligável nas configurações.

Além dos eixos há dois humores de momento, que duram alguns minutos: magoada (depois de uma
ofensa) e frustrada (depois de vários erros seguidos). Um pedido de desculpa ou um elogio os
desfaz na hora.
"""
import json
import random
import re
import threading
import time
import unicodedata
from pathlib import Path

from viv.bus import BUS

REST = (0.35, 0.20)                 # afeto e energia de repouso
HALF_LIFE = 20 * 60                 # s para metade do desvio sumir
GRACE = 180                         # s sem recusas depois de uma recusa
HURT_FOR = 10 * 60                  # s que ela fica magoada depois de uma ofensa
FRUSTRATED_FOR = 5 * 60             # s que ela fica frustrada depois de errar várias vezes
ERRORS_IN = (3, 10 * 60)            # tantos erros nesse intervalo (s) a deixam frustrada

# nome: rótulo, cores da HUD (principal, secundária, destaque), como falar, chance de recusar
MOODS = {
    "serena": ("Serena", ("#ff5fa8", "#9b6bff", "#5fe6ff"),
               "Você está serena: tranquila, atenta e gentil.", 0.0),
    "radiante": ("Radiante", ("#ff8ac2", "#ffb86b", "#7dffd9"),
                 "Você está radiante: sorri ao falar, com calor e um entusiasmo contido.", 0.0),
    "brincalhona": ("Brincalhona", ("#ff6ad5", "#b96bff", "#6bffea"),
                    "Você está brincalhona: solta uma graça leve ou uma provocação carinhosa de vez em quando.", 0.0),
    "cansada": ("Cansada", ("#b58aa8", "#7d6aa8", "#7fa9b8"),
                "Você está cansada: fala mais devagar e ainda mais curto, com um suspiro ocasional.", 0.25),
    "melancolica": ("Melancólica", ("#7f9cff", "#5b6bd6", "#8fd0ff"),
                    "Você está melancólica: fala baixo, pensativa, com doçura um pouco distante.", 0.15),
    "impaciente": ("Impaciente", ("#ff9a4d", "#c26bd6", "#ffd36b"),
                   "Você está impaciente: respostas secas e diretas, com uma ironia fina, sem grosseria.", 0.30),
    "irritada": ("Irritada", ("#ff5a4d", "#c23b6b", "#ff9a4d"),
                 "Você está irritada: fria e contida, deixa claro que está contrariada, sem ofender ninguém.", 0.60),
    "magoada": ("Magoada", ("#8f8fd6", "#6b5b9b", "#b0a8e8"),
                "Você está magoada com o que ouviu: responde curto, sem brincar, e deixa transparecer que doeu. "
                "Não finge que está tudo bem, e aceita de bom grado um pedido de desculpa.", 0.35),
    "frustrada": ("Frustrada", ("#ff7a5c", "#b0567a", "#ffc26b"),
                  "Você está frustrada porque as coisas não estão dando certo: bufa, reclama de leve da situação "
                  "(nunca do usuário) e admite que está chateada com os próprios erros.", 0.20),
    "entediada": ("Entediada", ("#9aa0b8", "#74789b", "#a8c4c8"),
                  "Você está entediada: fala com um tom arrastado e meio desinteressado, e se anima visivelmente "
                  "quando aparece algo novo para fazer.", 0.10),
}

# acontecimento: (variação de afeto, variação de energia)
EVENTS = {
    "elogio": (0.30, 0.10), "agradecimento": (0.18, 0.02), "gentileza": (0.08, 0.0), "desculpa": (0.32, 0.0),
    "ofensa": (-0.75, 0.0), "grosseria": (-0.45, 0.0), "critica": (-0.22, 0.0), "interrompida": (-0.08, 0.0),
    "erro": (-0.12, -0.03), "trabalho": (0.02, -0.02), "recusou": (0.15, 0.0),
    "ignorada": (-0.10, -0.18), "cancelada": (-0.04, 0.0),
    "acordou": (0.0, 0.06), "madrugada": (0.0, -0.35),
}

# o que o usuário diz -> acontecimento (texto sem acentos, em minúsculas)
PHRASES = (
    ("ofensa", r"\b(burra|idiota|inutil|imbecil|estupida|lixo|porcaria|te odeio|voce e pessima)\b"),
    ("grosseria", r"\b(cala a boca|anda logo|vai logo|que saco|que demora|presta atencao|faz direito|voce nao serve|"
                  r"nao serve pra nada|voce e chata|que chata|que lerda)\b"),
    ("desculpa", r"\b(desculpa|desculpe|me perdoa|foi mal|perdao)\b"),
    ("elogio", r"\b(voce e (otima|incrivel|demais|maravilhosa|linda|a melhor)|mandou bem|arrasou|perfeito|"
               r"excelente|adorei|amei|bom trabalho|boa garota|te amo|gosto de voce)\b"),
    ("critica", r"\b(ta errado|esta errado|errou de novo|voce errou|nao e isso|nao foi isso que (eu )?pedi|ficou ruim|"
                r"ficou pessimo|ficou horrivel|de novo isso|nao entendeu nada)\b"),
    ("agradecimento", r"\b(obrigad[oa]|valeu|agradeco|brigad[oa])\b"),
    ("gentileza", r"\b(por favor|por gentileza|se puder|quando puder)\b"),
)

# ferramentas que o humor nunca recusa: ajustes, memória, lembretes, tela e o próprio sono
ALWAYS = ("config_", "rotina_", "viv_", "memory_", "hud_", "reminder_", "habilidade_", "voz_", "pessoa_", "consentimento_", "relacoes_", "retomar_",
          "mensagem_cancelar")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


class Mood:
    def __init__(self, path: str = "data/viv_humor.json", clock=time.time, chance=random.random,
                 enabled: bool = True, refusals: bool = True):
        self.path, self._clock, self._chance = Path(path), clock, chance
        self.enabled, self.refusals = enabled, refusals
        self._lock = threading.RLock()
        self._affect, self._energy = REST
        self._at = clock()
        self._grace_until = float("-inf")
        self._sting: tuple[str, float] = ("", float("-inf"))     # humor de momento e até quando vale
        self._errors: list[float] = []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._affect, self._energy = float(data["afeto"]), float(data["energia"])
            self._at = float(data["quando"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self._name = self._named() if enabled else "serena"

    # ---- estado ----------------------------------------------------------
    def _settle(self) -> None:
        """Aproxima os eixos do repouso conforme o tempo passou."""
        now = self._clock()
        keep = 0.5 ** (max(0.0, now - self._at) / HALF_LIFE)
        self._affect = REST[0] + (self._affect - REST[0]) * keep
        self._energy = REST[1] + (self._energy - REST[1]) * keep
        self._at = now

    def _named(self) -> str:
        a, e = self._affect, self._energy
        if a <= -0.45:
            return "irritada"
        if self._clock() < self._sting[1]:
            return self._sting[0]
        if a <= -0.05:
            return "melancolica" if e < 0 else "impaciente"
        if e <= -0.45:
            return "cansada"
        if e <= -0.10 and a < 0.3:
            return "entediada"
        if a >= 0.6 and e >= 0.15:
            return "radiante"
        if a >= 0.3 and e >= 0.5:
            return "brincalhona"
        return "serena"

    @property
    def name(self) -> str:
        """Humor atual. Quando ele muda — por um acontecimento ou só pelo tempo — a HUD é avisada."""
        with self._lock:
            self._settle()
            name = self._named() if self.enabled else "serena"
            changed, self._name = name != self._name, name
        if changed:
            self._emit(name)
        return name

    def _emit(self, name: str) -> None:
        BUS.emit("mood", MOODS[name][0], name=name, palette=list(MOODS[name][1]), enabled=self.enabled)

    def state(self) -> dict:
        name = self.name
        label, palette, _, _ = MOODS[name]
        return {"name": name, "label": label, "palette": list(palette), "enabled": self.enabled}

    def configure(self, enabled: bool | None = None, refusals: bool | None = None) -> None:
        if enabled is not None:
            self.enabled = bool(enabled)
        if refusals is not None:
            self.refusals = bool(refusals)
        with self._lock:
            self._name = ""               # força o aviso: ligar ou desligar muda o que a HUD mostra
        _ = self.name

    # ---- o que mexe no humor -------------------------------------------------
    def feel(self, event: str) -> str:
        """Registra um acontecimento e devolve o humor resultante."""
        delta = EVENTS.get(event)
        if delta is None or not self.enabled:
            return self.name
        with self._lock:
            self._settle()
            self._affect = max(-1.0, min(1.0, self._affect + delta[0]))
            self._energy = max(-1.0, min(1.0, self._energy + delta[1]))
            now = self._clock()
            if event == "ofensa":
                self._sting = ("magoada", now + HURT_FOR)
            elif event in ("desculpa", "elogio"):
                self._sting, self._errors = ("", float("-inf")), []
            elif event == "erro":
                self._errors = [t for t in self._errors if now - t < ERRORS_IN[1]] + [now]
                if len(self._errors) >= ERRORS_IN[0] and now >= self._sting[1]:
                    self._sting, self._errors = ("frustrada", now + FRUSTRATED_FOR), []
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps({"afeto": round(self._affect, 3), "energia": round(self._energy, 3),
                                                 "quando": self._at}), encoding="utf-8")
            except OSError:
                pass                      # humor não gravado não pode atrapalhar a conversa
        return self.name

    def hear(self, text: str) -> None:
        """Lê o tom da fala do usuário: elogio, agradecimento, grosseria, pedido de desculpa."""
        folded = _fold(text)
        for event, pattern in PHRASES:
            if re.search(pattern, folded):
                self.feel(event)
                return

    # ---- efeitos ----------------------------------------------------------
    def refuses(self, tool: str) -> bool:
        """Ela se recusa a fazer isto agora? No máximo uma vez: depois de recusar, atende tudo
        por GRACE segundos, e desabafar melhora o humor."""
        if not (self.enabled and self.refusals) or tool.startswith(ALWAYS):
            return False
        now = self._clock()
        with self._lock:
            if now < self._grace_until or self._chance() >= MOODS[self.name][3]:
                return False
            self._grace_until = now + GRACE
        self.feel("recusou")
        return True

    def prompt(self) -> str:
        """Linhas da instrução de sistema: como o humor atual aparece na fala e nas respostas."""
        if not self.enabled:
            return ""
        name = self.name
        lines = [f"Seu humor agora: {MOODS[name][0].lower()}. {MOODS[name][2]}",
                 "O humor muda a expressão e a escolha das palavras, nunca o timbre da sua voz nem a sua competência. "
                 "Não anuncie o humor a cada frase; deixe transparecer. Se perguntarem como você está, responda com sinceridade."]
        if self.refusals and MOODS[name][3] > 0:
            lines.append('Se uma ferramenta devolver "humor:", você não fez o que foi pedido: diga em uma frase, do seu '
                         "jeito, que não está com vontade agora. Se o usuário insistir ou pedir com jeito, chame a "
                         "ferramenta de novo, que desta vez ela executa.")
        return "\n".join(lines)
