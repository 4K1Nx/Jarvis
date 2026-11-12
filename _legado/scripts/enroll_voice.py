"""Cadastro local da voz. Nao acessa Gemini, .env ou ferramentas do PC."""
import argparse
import sys
from pathlib import Path
from datetime import datetime
import shutil
import numpy as np
import yaml
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PHRASES = [
    'Oi, Viv. Hoje estou cadastrando minha voz com calma.',
    'Esta frase serve apenas para reconhecer a minha voz.',
    'Gosto de conversar usando meu tom natural, sem pressa.',
    'A minha assistente se chama Viv e fala em portugu\u00eas.',
    'Agora vou falar perto do microfone, como no dia a dia.',
    'Posso fazer perguntas e continuar a mesma conversa.',
    'Quero ouvir respostas claras e gentis durante o dia.',
    'Esta \u00e9 a \u00faltima frase do meu cadastro de voz.',
]

def validate_clip(audio, rate=16000):
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if len(samples) < rate * 2 or not np.isfinite(samples).all():
        raise ValueError('Use pelo menos dois segundos de audio valido.')
    if np.sqrt(np.mean(samples ** 2)) < .001:
        raise ValueError('Sinal muito baixo. Aproxime-se do microfone e tente novamente.')
    if np.mean(np.abs(samples) >= .99) > .01:
        raise ValueError('Audio saturado. Reduza o ganho antes de cadastrar.')
    return samples

def record(seconds, device):
    import sounddevice as sd
    audio = sd.rec(int(seconds*16000), samplerate=16000, channels=1,
                   dtype='float32', device=device)
    sd.wait()
    return validate_clip(audio.flatten())

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--owner', help='Seu nome, nao o nome da assistente')
    ap.add_argument('--wav', nargs='*', default=[])
    ap.add_argument('--seconds', type=float, default=5)
    args=ap.parse_args()
    if not 3 <= args.seconds <= 15:
        ap.error('Use entre 3 e 15 segundos por frase.')
    cfg=yaml.safe_load((ROOT/'config.yaml').read_text(encoding='utf-8'))
    path=Path(cfg['speaker_id']['voiceprint_path'])
    if not path.is_absolute():path=ROOT/path
    cfg['speaker_id']['voiceprint_path']=str(path)
    if path.exists():
        print('Ja existe cadastro. Uma copia sera preservada antes da substituicao.')
        if input('Digite SUBSTITUIR para refazer, ou Enter para cancelar: ').strip()!='SUBSTITUIR':
            print('Cancelado. Cadastro preservado.');return
    owner=(args.owner or input('Seu nome (proprietario): ')).strip()
    if not owner:ap.error('Informe seu nome.')
    from core.speaker_id import SpeakerID
    spk=SpeakerID(cfg)
    if spk.encoder is None:raise RuntimeError('Resemblyzer indisponivel. Consulte README_VIV.md.')
    clips=[]
    if args.wav:
        import soundfile as sf
        if len(args.wav)<3:ap.error('Forneca pelo menos tres gravacoes de 16 kHz.')
        for filename in args.wav:
            audio,rate=sf.read(filename,dtype='float32')
            if rate!=16000:raise ValueError('Os arquivos precisam estar em 16 kHz; nao foram alterados.')
            clips.append(validate_clip(audio if audio.ndim==1 else audio.mean(axis=1)))
    else:
        from core.audio_in import AudioInput
        mic=AudioInput(cfg)
        device=mic.resolve_device()
        print('Microfone: '+mic.resolved_name)
        print('Feche a Viv antes de gravar. Nenhuma frase executa comandos.')
        for index in range(max(3,cfg['speaker_id'].get('enroll_clips',8))):
            while True:
                input(f'[{index+1}] Leia apos Enter: '+PHRASES[index%len(PHRASES)])
                try:clips.append(record(args.seconds,device));break
                except ValueError as exc:print(str(exc))
            print('Frase capturada.')
    if path.exists():
        backup=path.with_name(path.name+'.backup-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        shutil.copy2(path,backup)
    spk.enroll(clips,owner)
    print('Cadastro salvo. Inicie a Viv novamente com .\\run.bat.')
    print('Os limiares de seguranca nao foram alterados. Audio bruto nao foi salvo.')

if __name__=='__main__':main()
