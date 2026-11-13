# Recupera??o da Viv ? 16/10/2026

## Causas e corre??es

- `web/viv.js` estava ausente. Recuperado de um objeto local Git
  `1c38d85fe171a75c302a4e2dc234718a04ddbaf7`, com os controles de transcri??o e diagn?stico.
  O Git n?o est? dispon?vel no PATH; n?o foram feitos reset, clean ou commits.
- O barge-in aceitava qualquer fala do microfone durante o TTS, sem refer?ncia da
  reprodu??o. O novo `core/playback_echo.py` compara o PCM com a reprodu??o conhecida,
  subtrai trechos fortemente correlacionados e mant?m voz independente/misturada.
  Mant?m refer?ncia por 500 ms ap?s a reprodu??o para atenuar a cauda de eco.
  ? um filtro de refer?ncia, N?O um cancelador ac?stico completo: reverbera??o,
  distor??o, ganho autom?tico e atrasos maiores podem escapar ? correla??o.
- O in?cio do microfone e do monitor de interrup??o agora evita duplica??o sequencial.
  O monitor anterior termina antes de outro assumir a fila. O bot?o de ativa??o
  tamb?m interrompe a reprodu??o sem aprovar a??es sens?veis.
- WebSocket do servidor agora observa desconex?o mesmo sem novos eventos, remove
  a inscri??o no barramento e cancela as tarefas associadas. Cliente evita conex?es
  duplicadas. Estado pendente de confirma??o tamb?m consta no snapshot existente.
- Caminhos de arquivos est?ticos do servidor agora s?o relativos ao pr?prio server.py.

## Arquivos desta recupera??o

web/viv.js (recuperado e ajustado), server.py, core/playback_echo.py (novo),
core/audio_in.py, core/tts.py, core/orchestrator.py, core/barge_in.py,
scripts/test_recovery.py (novo), scripts/test_hud.py e README_VIV.md.
Os testes regeneraram screenshots sint?ticos em artifacts/viv-1.2/.

## Valida??o executada

- 112 testes Python passaram: conversa, ferramentas, ?udio/VAD, wake word, pesquisa,
  comandos locais, pend?ncias, arquivos, lembretes, barge-in e recupera??o.
- HUD em Edge headless: estados, bot?es, confirma??o, transcri??o, Gemini simulado,
  fontes seguras, medidores separados, layout m?vel e aus?ncia de erros JS.
- FastAPI real via TestClient: GET /static/viv.js = 200; WebSocket entrega evento e
  libera inscri??o ao desconectar. Nenhuma rota fict?cia foi adicionada ? produ??o.
- Filtro: eco atrasado/atenuado, voz independente e voz misturada, cauda/expira??o.
  M?dia de 0,465 ms por quadro em 200 quadros sint?ticos nesta m?quina.
- Microfone configurado encontrado uma vez, ?ndice atual 1, formato 16 kHz mono aceito.
  N?o foi aberto stream nem capturado ?udio real.
- N?o havia servidor alcan??vel em 127.0.0.1:8765 ao fazer a verifica??o externa.

## O que conferir manualmente

1. Reiniciar com `.\run.bat`; abrir http://127.0.0.1:8765 e atualizar com Ctrl+F5.
2. Conferir HUD conectada; marcar Testar s? transcri??o, ativar e falar uma frase.
3. Desmarcar o teste, pedir uma resposta e ficar em sil?ncio: a Viv n?o deve reagir
   ? pr?pria sa?da. Repetir com fones e depois com o volume habitual das caixas.
4. Interromper dizendo ?Que horas s?o??; conferir que a fala para e o pedido ? capturado.
   O bot?o ATIVAR VIV ? uma alternativa independente de detec??o ac?stica.
5. Testar palmas e chamada ?Ei, Viv?. N?o executar a??es sens?veis para esta valida??o.

N?o foi testada a ac?stica real, a biometria, a gera??o Gemini, a s?ntese Edge online ou
uma a??o real no Windows. O Whisper Small permanece configurado; Medium n?o foi instalado
ou validado. As corre??es anteriores da Calculadora e do lembrete com prazo ao final
est?o presentes. Dados, mem?ria, credenciais, voiceprint e modelos n?o foram modificados.
