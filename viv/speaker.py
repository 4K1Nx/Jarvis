"""Reconhecimento de voz: quem está falando, e se é o dono cadastrado.

Um d-vector de 256 dimensões (Resemblyzer, CPU) é comparado por similaridade de
cosseno com o cadastro em data/voiceprint.json. Sem cadastro ou sem o encoder, a
pontuação é 0 e só o clique na HUD confirma ações perigosas.

O áudio analisado é só a fala do turno (sem silêncio nem a voz da própria Viv). Com
pelo menos LONG amostras de fala a identidade é decidida e guardada; um "sim" curto,
que sozinho não sustenta um vetor confiável, vale quando passa num limiar menor e o
dono foi reconhecido há pouco na mesma conversa. Outras pessoas ficam em
data/voiceprints.json, separado do cadastro do dono.
"""
import json
import os
import time

import numpy as np

from viv.bus import BUS

LONG = 24000          # 1,5 s de fala a 16 kHz: mínimo para decidir quem fala
FRESH = 90.0          # s em que a última identificação continua valendo
TRUST = 300.0         # s em que a voz do dono, reconhecida com segurança, mantém as permissões


class Speaker:
    def __init__(self, cfg: dict, clock=time.monotonic):
        s = cfg.get("speaker_id", {})
        self.path = s.get("voiceprint_path", "data/voiceprint.json")
        self.people_path = s.get("people_path", "data/voiceprints.json")
        self.threshold = float(s.get("privileged_threshold", 0.78))
        self.short_threshold = float(s.get("short_threshold", 0.62))
        self.owner = ""
        self.reference = None
        self.people: dict[str, np.ndarray] = {}
        self.current = {"name": "", "owner": False, "known": False, "score": 0.0, "at": float("-inf")}
        self.trusted_at = float("-inf")     # última vez que a voz do dono foi reconhecida com segurança
        self.last_score = 0.0
        self._clock = clock
        self._encoder = None
        self._enabled = bool(s.get("enabled", True))
        if self._enabled and os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as stream:
                    data = json.load(stream)
                self.reference = np.asarray(data["embedding"], dtype=np.float32)
                self.owner = data.get("owner", "")
            except (OSError, ValueError, KeyError):
                BUS.emit("card", "Cadastro de voz ilegível", kind="data",
                         body="Refaça com: python scripts/enroll_voice.py", ok=False)
        if self._enabled and os.path.exists(self.people_path):
            try:
                with open(self.people_path, encoding="utf-8") as stream:
                    self.people = {str(name): np.asarray(vec, dtype=np.float32)
                                   for name, vec in json.load(stream).items()}
            except (OSError, ValueError, AttributeError):
                self.people = {}

    @property
    def enrolled(self) -> bool:
        return self.reference is not None

    def warm(self) -> None:
        """Carrega o encoder antes da primeira fala, para a identificação não atrasar a conversa."""
        if self._enabled and self.enrolled:
            try:
                self._embed(np.zeros(16000, dtype=np.float32))
            except Exception:
                pass

    def _embed(self, audio: np.ndarray) -> np.ndarray:
        from resemblyzer import VoiceEncoder, preprocess_wav
        if self._encoder is None:
            self._encoder = VoiceEncoder("cpu", verbose=False)
        wav = preprocess_wav(np.asarray(audio, dtype=np.float32), source_sr=16000)
        vec = self._encoder.embed_utterance(wav)
        return vec / (np.linalg.norm(vec) + 1e-9)

    def _vector(self, audio):
        if not self._enabled or not self.enrolled or audio is None or len(audio) < 4000:
            return None
        try:
            return self._embed(audio)
        except Exception:
            return None

    def score(self, audio: np.ndarray) -> float:
        vec = self._vector(audio)
        self.last_score = 0.0 if vec is None else float(np.dot(vec, self.reference))
        return self.last_score

    def trusted(self) -> bool:
        """A voz do dono foi reconhecida nos últimos 5 minutos e, desde então, não falou ninguém que
        claramente não é ele. Uma fala só um pouco abaixo do limiar (ruído, fone, voz cansada) não
        tira a confiança; outra voz cadastrada, ou uma bem diferente da do dono, tira."""
        return self.enrolled and self._clock() - self.trusted_at <= TRUST

    def is_owner(self, audio: np.ndarray) -> bool:
        """Esta fala (em geral um “sim”) é do dono? Dentro da janela de confiança, sim; a fala já
        passou por hear(), que teria desfeito a confiança se fosse de outra pessoa."""
        score = self.score(audio)
        if self.trusted():
            return True
        if audio is not None and len(audio) >= LONG:
            return score >= self.threshold
        return score >= self.short_threshold and self.who()["owner"]

    def hear(self, audio: np.ndarray) -> dict:
        """Atualiza quem está falando a partir da fala de um turno e devolve a identidade atual.
        Fala curta demais não muda nada: a identidade anterior segue valendo enquanto for recente."""
        vec = self._vector(audio) if audio is not None and len(audio) >= LONG else None
        if vec is None:
            return self.who()
        owner_name = self.owner or "dono"
        scores = {owner_name: float(np.dot(vec, self.reference))}
        scores.update({name: float(np.dot(vec, ref)) for name, ref in self.people.items()})
        name, best = max(scores.items(), key=lambda item: item[1])
        known = best >= self.threshold
        if known and name == owner_name:
            self.trusted_at = self._clock()
        elif known or scores[owner_name] < self.short_threshold:
            self.trusted_at = float("-inf")       # outra pessoa falando: as permissões do dono caem
        before = (self.current["name"], self.current["known"])
        self.current = {"name": name if known else "", "owner": known and name == owner_name, "known": known,
                        "score": round(best, 3), "at": self._clock()}
        if before != (self.current["name"], known):
            BUS.emit("speaker", self.current["name"], known=known, owner=self.current["owner"])
        return self.who()

    def who(self) -> dict:
        """Identidade atual: nome, se é o dono e se alguém foi ouvido há pouco."""
        fresh = self._clock() - self.current["at"] <= FRESH
        return {"name": self.current["name"] if fresh else "", "owner": bool(self.current["owner"] and fresh),
                "known": bool(self.current["known"] and fresh), "heard": fresh}

    def stranger_present(self) -> bool:
        """Há pouco falou outra pessoa cadastrada (não o dono)? Voz apenas não reconhecida não conta:
        o reconhecimento falha com ruído, fone ou microfone diferente, e pedir confirmação a cada
        leitura do WhatsApp por isso atrapalhava o próprio dono."""
        who = self.who()
        return self.enrolled and who["known"] and not who["owner"] and not self.trusted()

    def _mean(self, clips: list[np.ndarray]) -> np.ndarray:
        ref = np.mean([self._embed(c) for c in clips], axis=0)
        return (ref / (np.linalg.norm(ref) + 1e-9)).astype(np.float32)

    def enroll(self, clips: list[np.ndarray], owner: str) -> None:
        ref = self._mean(clips)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as stream:
            json.dump({"owner": owner, "clips": len(clips), "embedding": ref.tolist()}, stream)
        self.reference, self.owner = ref, owner

    def enroll_person(self, clips: list[np.ndarray], name: str) -> None:
        """Cadastra outra pessoa da casa. Ela é reconhecida, mas não confirma ações perigosas."""
        self.people[name] = self._mean(clips)
        os.makedirs(os.path.dirname(self.people_path) or ".", exist_ok=True)
        with open(self.people_path, "w", encoding="utf-8") as stream:
            json.dump({n: v.tolist() for n, v in self.people.items()}, stream)
