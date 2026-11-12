# Viv Live — desenho

Data: 2026-11-12. Estado: aguardando revisão do usuário.

## Objetivo

Transformar a Viv numa assistente de voz no estilo "Jarvis": conversa natural em tempo real, em português brasileiro, que entende pedidos e manipula o PC, com uma HUD animada e reativa. A Viv é uma persona feminina, com identidade visual própria.

Sucesso significa: ela ouve sempre que é chamada, responde em menos de um segundo depois que o usuário para de falar, pode ser interrompida no meio da fala, executa ações no PC e não trava nem fecha sozinha.

## Problema atual

O pipeline de hoje é uma cascata (microfone → VAD → Whisper em CPU → Gemini REST → Edge TTS) com portões de palmas, biometria, filtro de eco e comandos locais por regex. O relatório `VIV_PENDENCIAS.md` registra 40 pedidos não compreendidos pelo modo de comandos locais, 17 falhas técnicas de conversa e 1 estouro de cota. O `data/native-crash.log` mostra um crash nativo quando a thread de interrupção e o TTS fecham o stream de áudio ao mesmo tempo. A biometria bloqueia quase todas as ferramentas quando a voz não é reconhecida. O `.venv` aponta para um Python de outra máquina e não funciona neste PC.

## Decisões tomadas com o usuário

| Tema | Decisão |
|---|---|
| Cérebro | Gemini Live API (áudio nativo), chave em `.env` (`GEMINI_API_KEY`), já configurada |
| Ativação | Atalho global + botão na HUD, "Ei, Viv" e duas palmas |
| Segurança | Ações comuns livres; ações perigosas exigem biometria de voz + confirmação, com clique na HUD como alternativa |
| Escopo | Decidido pelo assistente (lista abaixo) |
| HUD | Núcleo animado reativo + pop-ups, estilo IA de filme, identidade feminina original |

## Arquitetura

```
main.py            ponto de entrada; carrega config e .env, sobe tudo
viv/audio.py       um stream de entrada (16 kHz) e um de saída (24 kHz), abertos durante toda a execução
viv/wake.py        detectores usados enquanto a Viv dorme: palmas, "Ei, Viv", atalho global
viv/live.py        sessão Gemini Live: envia microfone, toca a resposta, trata interrupção,
                   chamadas de ferramenta, transcrições, reconexão e o tempo de inatividade
viv/safety.py      portão das ações perigosas (biometria + confirmação)
viv/speaker.py     verificação de voz (Resemblyzer), adaptada de core/speaker_id.py
viv/memory.py      fatos sobre o usuário em JSON, injetados na instrução de sistema
viv/bus.py         barramento de eventos para a HUD (adaptado de core/bus.py)
viv/tools/         ferramentas do PC, adaptadas das atuais
server.py          FastAPI: arquivos estáticos, WebSocket de eventos, ativação e confirmação
web/               HUD
scripts/enroll_voice.py   cadastro de voz, adaptado ao novo pacote
tests/             pytest
```

Cada módulo tem uma responsabilidade e fala com os outros por interfaces pequenas: `audio` entrega e recebe quadros PCM; `wake` devolve "acordar"; `live` consome áudio e um registro de ferramentas; `safety` decide se uma chamada de ferramenta pode rodar; a HUD só lê eventos do barramento.

### Ambiente

Python 3.12 instalado via winget (o PC só tem o 3.14, novo demais para as bibliotecas de áudio). Venv novo em `.venv`. Dependências principais: `google-genai`, `sounddevice`, `numpy`, `fastapi`, `uvicorn`, `pyyaml`, `python-dotenv`, `keyboard`, `pyautogui`, `psutil`, `pycaw`, `playwright`, `Pillow`, `ddgs`, `faster-whisper` (só para "Ei, Viv"), `resemblyzer` (biometria).

Modelo: `gemini-3.8-live`, configurável em `config.yaml`. Na implementação, a lista de modelos da chave é consultada para confirmar o nome e a cota grátis; se não estiver disponível, usa-se o modelo Live de áudio nativo mais recente que a chave ofereça.

### Estados e fluxo

Estados: `dormindo → ouvindo → pensando → falando → (executando) → ouvindo … → dormindo`.

1. **Dormindo.** Sem sessão aberta e sem gasto de cota. `wake.py` lê o microfone e espera um de quatro gatilhos: duas palmas, "Ei, Viv", `Ctrl+Alt+V` ou o botão da HUD.
2. **Acordar.** `live.py` abre a sessão com a instrução de sistema (persona, memória, data e hora) e as declarações de ferramentas. Um som curto confirma a ativação.
3. **Conversa.** O microfone é enviado em fluxo contínuo. O Gemini detecta início e fim de fala, responde em áudio e envia as transcrições dos dois lados, que vão para a HUD.
4. **Interrupção.** Quando o servidor sinaliza interrupção, a fila de reprodução é esvaziada na hora.
5. **Ferramentas.** Uma chamada de ferramenta passa por `safety.py`, roda em thread separada e devolve o resultado à sessão. Cada execução emite eventos para a HUD.
6. **Dormir.** Depois de 60 s sem fala (configurável), ou quando o usuário se despede, a sessão fecha e a Viv volta a dormir.

### Áudio

Os dois streams abrem uma vez no início e só fecham ao encerrar o programa. A reprodução usa uma fila; interromper é esvaziar a fila, sem fechar stream. Isso elimina a condição de corrida do crash registrado.

O microfone é escolhido por nome em `config.yaml`; se o nome não existir, usa-se o dispositivo padrão do Windows e a HUD mostra qual foi escolhido.

**Eco.** Com caixas de som, o microfone capta a voz da Viv e o modelo pode se interromper sozinho. Enquanto ela fala, o microfone só é enviado se o nível estiver bem acima do nível esperado da reprodução (portão por nível, limiar configurável). Com fones, a opção `audio.headphones: true` deixa o microfone aberto o tempo todo. Este é o maior risco do projeto e depende de teste com o equipamento real.

### Ativação

- **Palmas.** O detector de transiente de `core/audio_in.py` (RMS + taxa de cruzamento por zero, duas palmas entre 120 e 700 ms) é extraído para `wake.py` sem mudança de lógica.
- **"Ei, Viv".** Não existe modelo pronto de palavra de ativação para esse nome. Enquanto dorme, um detector de energia recorta trechos curtos de fala (até 3 s) e o Whisper `tiny` transcreve; se o texto contiver um dos apelidos (`Viv`, `Vivi`, `Vive`), a Viv acorda. O Whisper não roda com a sessão aberta.
- **Atalho.** `Ctrl+Alt+V` global, pela biblioteca `keyboard`. Acordada, o mesmo atalho a põe para dormir.
- **Botão.** A HUD chama `POST /api/wake`.

### Segurança

Ferramentas perigosas: `system.power`, `system.kill`, `fs.delete`, `fs.write`, `files.move`, `files.append_text`, `files.replace_text`, `desktop.run_command`. A lista fica em `config.yaml`.

Fluxo de uma ferramenta perigosa:

1. `safety.py` não executa. Guarda a ação como pendente, emite o cartão de confirmação na HUD e devolve ao modelo "aguardando confirmação do usuário".
2. O modelo pergunta em voz alta.
3. A ação só roda por um de dois caminhos:
   - **Voz:** a transcrição da fala seguinte do usuário, recebida do servidor, contém uma afirmação ("sim", "confirmo", "pode") e a pontuação biométrica do áudio dessa fala atinge o limiar.
   - **Clique:** o usuário aperta "Sim" no cartão da HUD.
4. Negação por voz, clique em "Não" ou 30 s sem resposta cancelam a ação.

A verificação é feita pelo código, a partir da transcrição e do áudio do usuário. O áudio vem de um buffer circular local com os últimos 6 s do microfone, do qual se usam só os trechos com fala. O modelo não tem ferramenta para confirmar por conta própria. Sem cadastro de voz, só o clique confirma. O cadastro existente (`data/voiceprint.json`), os limiares e o registro de auditoria (`data/audit.jsonl`) são preservados.

### Ferramentas

Mantidas e adaptadas para declarações de função do Gemini: `desktop.*` (abrir app, digitar, atalho, clicar, captura, comando), `system.*` (volume, status, processos, energia, encerrar processo), `files.*` e `fs.*`, `browser.*` (Playwright), `web.search`, `web.open`, `vision.analyze_screen`, `reminder.*`, memória (`memory.lembrar`, `memory.esquecer`).

Nova: `hud.mostrar(titulo, conteudo, tipo)`, para a Viv exibir texto, lista ou tabela num cartão.

Removidas: `docs.*`, `learning.stats`, `memory.archival_search`, `memory.recall_search`, `homeassistant.*`, `snapcast.*`, `routine.daily`, `vision.read_screen_local`.

Os nomes passam a usar `_` em vez de `.` se a API exigir. Uma ferramenta que falha devolve a mensagem de erro ao modelo, que a explica ao usuário; a HUD mostra o cartão com falha.

### Memória

`data/viv_memoria.json` guarda fatos curtos sobre o usuário. A Viv grava e apaga pelos dois comandos de memória. Os fatos entram na instrução de sistema ao abrir cada sessão. As transcrições da sessão anterior (últimos turnos) também entram, para dar continuidade depois de dormir.

### HUD

HTML, CSS e JavaScript puros, servidos pelo FastAPI. O `run.bat` abre a HUD em modo aplicativo do Edge (`--app=`), em janela própria.

**Núcleo.** Orbe em canvas com anéis concêntricos, partículas e onda circular. A amplitude vem do nível real de áudio: microfone ao ouvir, saída ao falar. Movimento por estado: respiração lenta (dormindo), anéis abertos com onda do microfone (ouvindo), anéis acelerados com partículas convergindo (pensando), onda pulsando com a fala (falando), arcos de progresso (executando), tremor vermelho (erro). Paleta violeta-rosa com acentos em ciano, traços finos e curvos, definida em variáveis CSS.

**Pop-ups.** Cartões entram deslizando em volta do núcleo, com linha conectora, e somem depois de alguns segundos. Tipos: ação executada, pesquisa com fontes, visão com miniatura da tela, dado (lembrete, hora, sistema), conteúdo livre (`hud.mostrar`) e confirmação com contagem regressiva e botões.

**Legenda.** A fala do usuário e a da Viv aparecem ao vivo abaixo do núcleo.

**Eventos** pelo WebSocket: `state`, `level` (microfone e saída), `transcript`, `card`, `confirm`, `error`.

### Erros

- Queda de conexão: reconexão automática com espera crescente; a HUD mostra "reconectando".
- Cota ou autenticação: som de erro curto (gerado localmente) e cartão de erro com a causa; a Viv dorme.
- Microfone ausente ou em uso: a HUD mostra o erro e o programa continua, aceitando o botão para tentar de novo.
- Falhas continuam sendo contadas por categoria em `VIV_PENDENCIAS.md`, como pede o `AGENTS.md`.

## Limpeza do repositório

- O código do pipeline antigo vai para `_legado/`: `core/`, `tools/` (depois de adaptado), `training/`, `eval/`, `scripts/` de teste do pipeline antigo, `README.md` (JARVIS-6), `UPGRADE_NOTES.md`, `requirements*.txt`. Nada é apagado, porque quase tudo está sem commit.
- Os três venvs saem do índice do git e entram no `.gitignore`. Os dois venvs antigos só são apagados do disco com autorização do usuário.
- Não são tocados: `.env`, `data/`, `teste_voz.py`, `teste_viv.mp3`, `AGENTS.md`, `VIV_PENDENCIAS.md`.
- `README_VIV.md` é reescrito para a nova arquitetura.
- Nenhum commit sem autorização.

## Testes

pytest, sem rede e sem microfone:

- `safety`: ação perigosa não roda sem confirmação; afirmação por voz com biometria aprovada roda; biometria reprovada exige clique; negação e tempo esgotado cancelam; o modelo não consegue confirmar.
- registro de ferramentas: conversão para declarações do Gemini, despacho, erro devolvido como texto.
- palmas: sinais sintéticos de duas palmas, uma palma, fala e ruído.
- "Ei, Viv": casamento de apelidos sobre transcrições.
- `live`: máquina de estados com sessão falsa (acordar, interrupção esvazia a fila, chamada de ferramenta, inatividade, reconexão).
- servidor: WebSocket entrega eventos; `/api/wake` e confirmação funcionam.

Validação com o usuário, por roteiro: microfone e caixas reais, cada forma de ativação, interrupção, eco com e sem fone, três ações no PC, uma ação perigosa com confirmação por voz e por clique.

## Fora do escopo desta versão

Overlay transparente sobre o desktop, modelo local, RAG de documentos, fine-tuning, casa inteligente, rotinas proativas, palavra de ativação treinada sob medida.

## Riscos

1. **Eco com caixas de som.** Mitigado pelo portão por nível; pode exigir ajuste de limiar ou uso de fones.
2. **Cota grátis da Live API.** Limite por sessão e por dia a confirmar com a chave real.
3. **"Ei, Viv" por Whisper `tiny`.** Nome curto pode gerar falhas ou disparos falsos; palmas e atalho continuam como alternativa.
4. **Biometria em falas curtas.** Um "sim" tem pouco áudio; o clique na HUD cobre a falha.
