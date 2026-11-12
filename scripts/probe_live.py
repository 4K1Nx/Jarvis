"""Sonda da Gemini Live API: confere a chave, lista os modelos Live e faz uma troca curta.

Uso: .venv\\Scripts\\python.exe scripts\\probe_live.py ["texto a enviar"] [--tools]
Nunca imprime a chave. Com --tools, registra as ferramentas reais e executa as chamadas.
"""
import asyncio
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


async def main() -> int:
    load_dotenv()
    import truststore
    truststore.inject_into_ssl()   # usa os certificados do Windows
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    key = os.environ.get(cfg["live"]["api_key_env"], "")
    if not key:
        print("Chave ausente: defina", cfg["live"]["api_key_env"], "no .env")
        return 1
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=key, http_options={"api_version": cfg["live"].get("api_version", "v1beta")})
    names = sorted(m.name for m in client.models.list())
    live = [n for n in names if "live" in n or "native-audio" in n]
    print("Total de modelos:", len(names)); print("Modelos Live da chave:", live)
    print("Flash:", [n for n in names if "flash" in n][:40])
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    text = args[0] if args else "Diga olá em português, em uma frase."
    use_tools = "--tools" in sys.argv
    config = {
        "response_modalities": ["AUDIO"],
        "speech_config": {"voice_config": {"prebuilt_voice_config": {"voice_name": cfg["live"]["voice"]}},
                          "language_code": cfg["live"]["language"]},
        "output_audio_transcription": {},
        "system_instruction": "Você é a Viv, assistente em português brasileiro. Responda em uma frase.",
    }
    ctx = None
    if use_tools:
        from viv.tools import registry
        registry.load_all()
        ctx = registry.Context(cfg, client=client)
        config["tools"] = [{"function_declarations": registry.declarations()}]
        config["system_instruction"] += " Use as ferramentas para agir no computador."
    model = cfg["live"]["model"]
    print("Conectando em", model)
    audio_bytes, said, fields = 0, [], set()
    async with client.aio.live.connect(model=model, config=config) as session:
        await session.send_realtime_input(text=text)
        async for msg in session.receive():
            fields |= {k for k, v in msg.model_dump(exclude_none=True).items()}
            if msg.data:
                audio_bytes += len(msg.data)
            if msg.tool_call:
                responses = []
                for call in msg.tool_call.function_calls:
                    print("tool_call:", call.name, call.args)
                    if not use_tools:
                        result = "ok"
                    elif registry.is_dangerous(call.name, cfg):
                        result = "recusado: a sonda não executa ações perigosas"
                    else:
                        result = registry.call(call.name, dict(call.args or {}), ctx)
                    print("  ->", result[:200])
                    responses.append(types.FunctionResponse(id=call.id, name=call.name, response={"result": result}))
                await session.send_tool_response(function_responses=responses)
            sc = msg.server_content
            if sc:
                fields |= {"server_content." + k for k in sc.model_dump(exclude_none=True)}
                if sc.output_transcription and sc.output_transcription.text:
                    said.append(sc.output_transcription.text)
                if sc.turn_complete:
                    break
    print("Campos recebidos:", sorted(fields))
    print("Áudio recebido:", audio_bytes, "bytes;", round(audio_bytes / 48000, 1), "s")
    print("Transcrição:", "".join(said))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:
        print("FALHA:", type(exc).__name__, str(exc)[:500])
        sys.exit(2)
