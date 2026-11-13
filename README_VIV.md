# Viv

Assistente de voz em tempo real para Windows, em português brasileiro. A Viv conversa com naturalidade, pode ser interrompida no meio da fala e age no computador: abre aplicativos, digita, clica, lê a tela, navega, pesquisa e mexe em arquivos. Uma HUD animada mostra o que ela ouve, diz e faz.

O cérebro é a Gemini Live API (áudio nativo). O áudio do microfone e as capturas de tela usadas na análise visual são enviados ao Google durante a conversa. Enquanto a Viv dorme, nada é enviado.

## Como usar

1. Dê dois cliques em `run.bat`. A HUD abre numa janela própria.
2. Acorde a Viv de um destes jeitos:
   - diga "Ei, Viv";
   - bata duas palmas;
   - aperte `Ctrl+Alt+V`;
   - clique em **Ativar Viv** na HUD.
3. Fale normalmente. Para interromper, fale por cima dela.
4. Ela dorme sozinha depois de 60 segundos de silêncio, quando você se despede, ou com `Ctrl+Alt+V` de novo.

Exemplos de pedidos:

- "abre o WhatsApp", "abre a Steam", "quais aplicativos eu tenho?"
- "como está o tempo em Vila Velha?" (abre o painel de clima)
- "pesquisa sobre placas de vídeo" (painel com as fontes e guias no navegador)
- "otimiza meu PC", "limpa os arquivos temporários" (diagnóstico e limpeza)
- "aumenta o volume para 60", "o que tem na minha tela?"
- "me avisa quando o download terminar" (ela vigia a tela e te chama)
- "tenho e-mail novo?", "lê o segundo"
- "desinstala o 7-Zip", "quais programas eu tenho?"
- "meu nome é João", "eu uso fones", "inicia junto com o Windows", "eu acordo às sete nos dias úteis"
- "quais erros você teve?", "o que deu errado no computador hoje?"
- "me lembra de tomar água em vinte minutos"

### A tela

- **Painel à esquerda:** a informação que você pediu (clima, pesquisa, listas, tabelas, diagnóstico). Fica até você fechar no ×, pedir outra coisa ou passar pouco mais de um minuto.
- **Avisos à direita:** cada ação executada. Somem sozinhos.
- **Cartão central:** confirmação de ação perigosa.

### Configurações e rotina

A engrenagem no canto da HUD abre os ajustes: nome, cidade, fones, sensibilidade da interrupção, tempo até dormir, formas de acordar, início com o Windows, boas-vindas e e-mail. Embaixo fica a rotina, com hora, dias e descrição.

A Viv altera os mesmos ajustes por voz. Tudo fica em `data/viv_config.json`. Um ajuste novo acrescentado em `viv/settings.py` aparece sozinho na tela e passa a ser conhecido por ela.

Na hora de cada item da rotina, ela avisa em voz alta.

### Iniciar com o Windows e boas-vindas

Com "Abrir junto com o Windows" ligado, um atalho na pasta Inicializar abre a Viv quando o computador liga. Ela então dá as boas-vindas com a hora, o clima da sua cidade, a rotina do dia, lembretes, e-mails não lidos, espaço em disco e erros recentes. O mesmo resumo aparece no painel. Para desligar: o ajuste na HUD, ou "Viv, não inicia mais com o Windows".

### Vigia da tela

"Me avisa quando o download terminar" faz a Viv olhar a tela a cada minuto, mesmo dormindo, e te chamar quando acontecer. Cada olhada envia uma captura da tela ao Gemini. "Para de vigiar" encerra. O limite padrão é de três horas.

### E-mail

A Viv lê a caixa de entrada por IMAP: lista não lidos, busca e lê uma mensagem. Ela não envia, não apaga e não marca como lido. O conteúdo dos e-mails que ela lê é enviado ao Gemini para ser resumido.

1. Em Configurações, preencha **E-mail** (para Gmail o servidor já vem certo).
2. Crie uma senha de app em `myaccount.google.com/apppasswords` (exige verificação em duas etapas).
3. Acrescente ao `.env`: `VIV_EMAIL_SENHA=a-senha-de-app` e reinicie a Viv.

### Humor

A Viv tem humores (serena, radiante, brincalhona, cansada, melancólica, impaciente, irritada). Elogios, agradecimentos e pedidos de desculpa melhoram o humor; grosserias, ferramentas que falham e a madrugada pioram; com o tempo ela volta a ficar serena. O humor muda as cores da tela, a expressão da fala e o jeito de responder, e aparece no topo da HUD.

De mau humor ela pode se negar a fazer um pedido uma vez. Insistir sempre funciona: depois de uma recusa ela atende tudo por três minutos. Ajustes, lembretes, memória e o comando de dormir nunca são recusados. Em Configurações, “Humor” desliga tudo e “Humor pode recusar pedidos” desliga só as recusas.

### Barra de progresso

Tarefas que passam de um segundo (pesquisa profunda, programar, criar documentos, WhatsApp, limpeza) mostram uma barra fina acima da legenda com a etapa atual. Ações rápidas não mostram nada.

### WhatsApp e pessoas

“Viv, tem mensagem nova?”, “lê a conversa da minha mãe”, “manda para o chefe que eu chego às nove”. Ela usa o WhatsApp Web no navegador que já controla: na primeira vez, abre a página para você ler o QR code (WhatsApp > Aparelhos conectados); a sessão fica guardada em `data/browser-profile/`. Enviar sempre pede confirmação, e o cartão mostra o nome real do contato e o texto exato.

Conte quem é quem (“a Maria Silva é minha mãe”) e a Viv guarda a pessoa com um apelido ou a relação, em `data/viv_pessoas.json`, e passa a se referir a ela assim. “Viv, quem você conhece?” mostra a lista.

O WhatsApp não oferece API para conta pessoal; a Viv lê a página como você leria. Se o WhatsApp mudar a página, os seletores ficam no topo de `viv/tools/whatsapp.py`. As mensagens lidas são enviadas ao Gemini para ela resumir.

### Conversas e planos com pessoas próximas

A Viv ajuda a lembrar, planejar e escrever; o que dizer, quando falar e o que fazer é sempre escolha sua. Ela não mede afeto, não conta respostas e não cria urgência a partir do jeito de alguém escrever.

| Fluxo | Como usar | Liga / pausa |
|---|---|---|
| Rascunho e envio | “Viv, me ajuda a responder a Bia”. Ela mostra destinatário e texto; você diz enviar, editar, copiar ou cancelar. Enviar pede confirmação daquele destinatário e daquele texto; mudou um deles, confirma de novo. Uma falha de resultado incerto nunca é repetida sem conferir a conversa. | Sempre disponível. Sem WhatsApp conectado, “copiar” põe o texto na área de transferência. |
| Trecho selecionado | Copie o trecho (Ctrl+C) e diga “Viv, olha o que eu copiei”. | Sempre disponível; é o modo manual. |
| Tom por pessoa | “Com a Bia eu escrevo curto e carinhoso”, “guarda essa mensagem minha como exemplo”. | — |
| Lembrete de retomar | “Me lembra de responder a Bia” (20 min por padrão). Depois: adiar, dispensar ou feito. | Só quando você pede. Horário silencioso em Configurações. |
| Presentes e aniversário | “O aniversário da Bia é 20/03”, “guarda a ideia: girassóis”. 14 dias antes aparecem até três ideias. | Apague com “Viv, apaga a ideia dos girassóis”. |
| Encontros | “Viv, planeja um encontro com a Bia”; “guarda este lugar”. | Revisão semanal: Configurações > “Revisão semanal de encontros”. |
| Notas de evento | “Jantar sábado às 20h, me lembra de perguntar da viagem”. Meia hora antes as notas aparecem. | Apague a nota ou o evento por voz. |
| Sugestão de cuidado | Cadastre o plantão dela; com chuva ou turno longo, a Viv sugere oferecer algo. | Exige o consentimento “cuidado” da pessoa. |
| Gestos ocasionais | “Me lembra de um gesto para a Bia a cada seis a oito semanas”. | “Pausa os gestos da Bia”. |
| Depois de um conflito | Só a seu pedido, sobre o trecho que você escolher. | — |
| Resumo semanal | Mensagens a retomar, planos, datas e lembretes. | Configurações > “Resumo semanal privado”. |

Os lembretes pessoais aparecem só na tela, sem conteúdo de conversa; “Lembretes pessoais em voz alta” muda isso.

**Consentimento.** Tudo o que usa mensagens ou dados de outra pessoa começa desligado. “Viv, a Bia concordou com o acompanhamento” abre um cartão que diz o que será usado, o que fica salvo, por quanto tempo e se passa pelo Gemini; só vale depois do seu “sim”. Finalidades: `acompanhamento`, `presentes`, `agenda`, `cuidado`, `endereco`. “O que você guarda sobre a Bia?” mostra tudo; “revoga o consentimento da Bia” para a leitura e apaga o que dependia dele. Consentimento vencido é revogado sozinho. Os dados ficam em `data/viv_relacoes.json` (marcas, datas e notas; nunca o texto das conversas) e os rascunhos só existem na memória do programa.

**Ainda depende de configuração:** não há agenda conectada (os encontros usam a sua rotina e o que a pessoa compartilhou, e você confirma os horários), não há Notion (as listas são locais) e a Viv não faz compras, reservas nem pedidos de entrega.

### Desinstalar programas

"Desinstala o 7-Zip" usa o winget e sempre pede confirmação, mostrando o nome exato do programa. Se o nome falado serve para mais de um programa, ela pergunta qual em vez de escolher.

### Erros

Toda falha (ferramenta, conexão) fica em `data/viv_erros.jsonl`, com a origem e a mensagem, sem os argumentos nem as falas. "Quais erros você teve?" mostra o relatório. "O que deu errado no computador?" mostra os erros do log de eventos do Windows.

### Limpeza do PC

"Otimiza meu PC" mostra o diagnóstico: disco, memória, processos pesados, espaço recuperável e o que inicia com o Windows. A limpeza apaga arquivos temporários e caches de navegador com mais de um dia, esvazia a lixeira e limpa o cache de DNS. Ela sempre pede confirmação. Arquivos em uso são ignorados.

## Instalação

Precisa de Windows 10 ou 11 e Python 3.12.

```bat
winget install -e --id Python.Python.3.12 --source winget
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python.exe -m pip install resemblyzer --no-deps
.venv\Scripts\python.exe -m pip install librosa scipy webrtcvad-wheels
.venv\Scripts\python.exe -m playwright install chromium
```

Crie o arquivo `.env` na pasta do projeto com a chave do Google AI Studio:

```
GEMINI_API_KEY=sua-chave
```

As três linhas de `torch`, `resemblyzer` e `librosa` só servem para a biometria de voz. Sem elas a Viv funciona, e as ações perigosas passam a ser confirmadas apenas pelo clique na HUD.

## Segurança

Ações comuns rodam direto. Estas pedem confirmação antes de executar:

| Ação | Ferramenta |
|---|---|
| Desligar, reiniciar, suspender, bloquear | `system_power` |
| Encerrar um aplicativo | `system_kill` |
| Apagar arquivo ou pasta | `fs_delete` |
| Limpar temporários, caches e lixeira | `system_limpeza` |
| Desinstalar um programa | `system_desinstalar` |
| Gravar por cima, mover, acrescentar ou substituir texto | `fs_write`, `files_move`, `files_append_text`, `files_replace_text` |
| Rodar comando no shell | `desktop_run_command` |

A Viv pergunta em voz alta e um cartão aparece na HUD. A ação só roda se você:

- disser "sim" (ou "confirmo", "pode") **e** a sua voz bater com o cadastro; ou
- clicar em **Sim** no cartão.

"Não", "cancela", o botão **Não** ou 30 segundos sem resposta cancelam. Quem decide é o programa, a partir da sua fala e do seu áudio; o modelo não tem como confirmar sozinho. A lista fica em `safety.dangerous`, no `config.yaml`.

### Cadastro de voz

Com a Viv fechada:

```bat
.venv\Scripts\python.exe scripts\enroll_voice.py
```

Você lê oito frases de cinco segundos. Só o vetor da voz é salvo, em `data/voiceprint.json`; o áudio não é guardado. Sem cadastro, a confirmação por voz fica desligada e vale só o clique.

A Viv reconhece quem fala a cada turno, usando só a fala (sem silêncio nem a voz dela), e mostra o nome no topo da tela. Um “sim” curto confirma uma ação quando o dono foi reconhecido há pouco na mesma conversa; dizer “sim, pode fazer” é mais confiável. Se uma voz que não é a do dono pedir WhatsApp ou e-mail, ela pede confirmação antes de mostrar.

```bat
.venv\Scripts\python.exe scripts\enroll_voice.py --testar         mostra a sua pontuação contra o cadastro
.venv\Scripts\python.exe scripts\enroll_voice.py --pessoa Ana     cadastra outra pessoa da casa
```

Se `--testar` ficar abaixo do limiar no uso normal, refaça o cadastro no microfone do dia a dia ou ajuste `speaker_id.privileged_threshold` (padrão 0,78). Outras pessoas ficam em `data/voiceprints.json`: são reconhecidas pelo nome, mas não confirmam ações perigosas.

A biometria por voz evita que outra pessoa na sala dê ordens perigosas. Ela não protege contra uma gravação da sua voz.

## Ajustes (`config.yaml`)

| Chave | Para que serve |
|---|---|
| `audio.input_device_name` | Parte do nome do microfone. `null` usa o padrão do Windows. |
| `audio.headphones` | `true` se você usa fones: o microfone fica aberto enquanto a Viv fala e a interrupção fica mais sensível. |
| `audio.barge_in_rms` | Sem fones, é o volume mínimo da sua voz para interromper a Viv. Se ela se interrompe sozinha, aumente (ex.: `0.12`). Se você não consegue interromper, diminua (ex.: `0.05`). |
| `assistant.idle_seconds` | Segundos de silêncio até dormir. |
| `wake.aliases` | Como o nome pode ser ouvido ("Viv", "Vivi", "Vive"). |
| `wake.name_enabled`, `wake.clap_enabled` | Liga e desliga a ativação por nome e por palmas. |
| `wake.hotkey` | Atalho global. |
| `live.voice` | Voz da Viv. |
| `live.model` | Modelo Live. |

## Estrutura

```
main.py            ponto de entrada
server.py          servidor local da HUD (só 127.0.0.1)
viv/audio.py       microfone e alto-falante, dois streams fixos
viv/wake.py        palmas, "Ei, Viv" e atalho, usados enquanto ela dorme
viv/live.py        sessão Gemini Live e máquina de estados
viv/persona.py     instrução de sistema (personalidade e regras)
viv/safety.py      confirmação das ações perigosas
viv/speaker.py     verificação de voz
viv/memory.py      fatos sobre você e últimos turnos (data/viv_memoria.json)
viv/reminders.py   lembretes (data/jobs.json)
viv/settings.py    configurações e rotina (data/viv_config.json)
viv/routine.py     avisos da rotina na hora marcada
viv/briefing.py    boas-vindas ao ligar o PC
viv/autostart.py   atalho de início com o Windows
viv/watch.py       vigia da tela
viv/errors.py      registro de erros (data/viv_erros.jsonl)
viv/tools/         ferramentas do PC
web/               HUD
scripts/           cadastro de voz e sonda da API
tests/             testes automáticos
_legado/           código da versão anterior, guardado para consulta
```

## Testes

```bat
.venv\Scripts\python.exe -m pytest -q
```

Os testes não usam rede, microfone nem a chave. Para conferir a chave e a API de verdade:

```bat
.venv\Scripts\python.exe scripts\probe_live.py
```

Para ver só a HUD, com eventos de demonstração: `run.bat --demo`.

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| "Chave do Gemini ausente ou inválida" | Confira o `.env`. Rode `scripts\probe_live.py`. |
| "Cota do Gemini atingida" | A camada grátis tem limite. Espere ou ative o faturamento no Google AI Studio. |
| A Viv se interrompe sozinha | O microfone está captando as caixas. Use fones (`audio.headphones: true`) ou aumente `audio.barge_in_rms`. |
| Não consigo interrompê-la | Diminua `audio.barge_in_rms` ou use fones. |
| Não acorda com "Ei, Viv" | Fale um pouco mais alto e pausado, ou use palmas ou o atalho. O nome é detectado por um modelo pequeno e pode falhar. |
| Palmas não acordam | Bata duas palmas firmes, com intervalo de um quarto a meio segundo. |
| Microfone errado | Veja o nome no canto da HUD e ajuste `audio.input_device_name`. |
| O atalho não funciona | Outro programa pode usar a mesma combinação. Troque `wake.hotkey`. |

As falhas são contadas por categoria em `VIV_PENDENCIAS.md`.

## Criação: programar, documentos, pesquisa e habilidades

| Você diz | A Viv usa | O que acontece |
|---|---|---|
| “Cria um jogo da cobrinha” / “muda a cor” / “conserta o erro” | `codigo_criar` | Escreve o projeto em `Documentos\Viv\Projetos\<nome>`, confere a sintaxe e guarda cada passo num histórico git. |
| “Roda o projeto” | `codigo_executar` | Pede confirmação, instala dependências na primeira vez e mostra a saída. O erro fica guardado para o próximo ajuste. |
| “Desfaz a última alteração” | `codigo_desfazer` | Volta um passo (pede confirmação). |
| “Faz uma apresentação sobre…” / “uma planilha de gastos” / “um PDF com…” | `documento_criar` | Gera Word, PDF, slides ou planilha em `Documentos\Viv\Documentos` e abre. |
| “Resume esse PDF” | `documento_ler` | Lê PDF, Word, PowerPoint e Excel. |
| “Pesquisa a fundo sobre…” | `pesquisa_profunda` | Várias buscas, leitura das páginas e relatório com fontes numeradas. |
| “Quando eu falar modo trabalho, abra…” | `habilidade_salvar` | Guarda a sequência e passa a segui-la pelo nome. |
| “Está tudo funcionando com você?” | `viv_diagnostico` | Tabela com conexão, voz, e-mail, bibliotecas e erros recentes. |

Os cartões da HUD têm uma barrinha que encolhe até a hora de sair (avisos: 8 s; painéis: 75 s). Passar o mouse
em cima pausa o tempo. Os painéis aceitam markdown simples: títulos, negrito, listas, tarefas, tabelas e código.

Pastas faladas (“Área de Trabalho”, “Downloads”, “Documentos”) apontam para as pastas reais do Windows, mesmo
quando o OneDrive as mudou de lugar.
