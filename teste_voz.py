import sounddevice as sd
from faster_whisper import WhisperModel

print("Carregando o reconhecimento de voz...")
modelo = WhisperModel("small", device="cpu", compute_type="int8")

print("Fale uma frase durante 7 segundos!")
audio = sd.rec(
    7 * 16000,
    samplerate=16000,
    channels=1,
    device=1,
    dtype="float32"
)
sd.wait()

print("Viv está tentando entender...")
segmentos, info = modelo.transcribe(
    audio.flatten(),
    language="pt",
    beam_size=5
)

texto = " ".join(segmento.text for segmento in segmentos)

print("Você disse:", texto)