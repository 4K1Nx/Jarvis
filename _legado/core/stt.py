"""faster-whisper small, CPU int8 — avoids CUDA/cuBLAS dependency."""
from faster_whisper import WhisperModel
from core.bus import BUS


class STT:
    def __init__(self, cfg: dict):
        s = cfg["stt"]
        self.cfg = s

        # Force CPU mode so Faster-Whisper does not require CUDA/cuBLAS DLLs.
        device = "cpu"
        compute_type = "int8"

        BUS.emit(
            "stt",
            f"loading faster-whisper {s['model']} on {device} ({compute_type})"
        )

        self.model = WhisperModel(
            s["model"],
            device=device,
            compute_type=compute_type,
            local_files_only=True,
        )

    def transcribe(self, audio, on_partial=None) -> str:
        segments, _info = self.model.transcribe(
            audio,
            language=self.cfg.get("language") or None,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )

        text = ""
        for seg in segments:
            text += seg.text

            if on_partial and self.cfg.get("first_partial_routing"):
                on_partial(text.strip())
                BUS.emit("stt", f'partial → "{text.strip()}"')

        text = text.strip()
        BUS.emit("stt", f'final → "{text}"')
        return text

    def transcribe_wake(self, audio) -> str:
        """Private local wake check. No event, history, cloud call or disk write."""
        segments, _ = self.model.transcribe(
            audio, language=self.cfg.get('language') or 'pt', beam_size=1,
            vad_filter=True, condition_on_previous_text=False,
            initial_prompt='Nome próprio da assistente: Viv.',
            max_new_tokens=48, repetition_penalty=1.15,
            temperature=0.0, compression_ratio_threshold=None)
        segments = list(segments)
        # Do not execute a request that may have been cut at the decoding limit.
        if sum(len(getattr(segment, 'tokens', [])) for segment in segments) >= 48:
            return ''
        return ''.join(segment.text for segment in segments).strip()
