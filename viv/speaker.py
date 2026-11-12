"""Verificação de voz: a fala é do dono cadastrado?

Um d-vector de 256 dimensões (Resemblyzer, CPU) é comparado por similaridade de
cosseno com o cadastro em data/voiceprint.json. Sem cadastro ou sem o encoder, a
pontuação é 0 e só o clique na HUD confirma ações perigosas.
"""
import json
import os

import numpy as np

from viv.bus import BUS


class Speaker:
    def __init__(self, cfg: dict):
        s = cfg.get("speaker_id", {})
        self.path = s.get("voiceprint_path", "data/voiceprint.json")
        self.threshold = float(s.get("privileged_threshold", 0.82))
        self.owner = ""
        self.reference = None
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

    @property
    def enrolled(self) -> bool:
        return self.reference is not None

    def _embed(self, audio: np.ndarray) -> np.ndarray:
        from resemblyzer import VoiceEncoder, preprocess_wav
        if self._encoder is None:
            self._encoder = VoiceEncoder("cpu", verbose=False)
        wav = preprocess_wav(np.asarray(audio, dtype=np.float32), source_sr=16000)
        vec = self._encoder.embed_utterance(wav)
        return vec / (np.linalg.norm(vec) + 1e-9)

    def score(self, audio: np.ndarray) -> float:
        if not self._enabled or not self.enrolled or audio is None or len(audio) < 4000:
            return 0.0
        try:
            return float(np.dot(self._embed(audio), self.reference))
        except Exception:
            return 0.0

    def is_owner(self, audio: np.ndarray) -> bool:
        return self.score(audio) >= self.threshold

    def enroll(self, clips: list[np.ndarray], owner: str) -> None:
        ref = np.mean([self._embed(c) for c in clips], axis=0)
        ref = ref / (np.linalg.norm(ref) + 1e-9)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as stream:
            json.dump({"owner": owner, "clips": len(clips), "embedding": ref.tolist()}, stream)
        self.reference, self.owner = ref.astype(np.float32), owner
