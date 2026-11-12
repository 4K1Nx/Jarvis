# Viv 1.2 — conversa por voz no Windows 11

Configuração: Python 3.11, Ryzen 5 4600G, Whisper Small CPU/int8 em português, Gemini 2.5 Flash e Edge TTS `pt-BR-FranciscaNeural`. HUD e duas palmas preservadas. O nome da assistente é `assistant.name`; `speaker_id.owner_name` é o nome do usuário (provisoriamente `usuário`). O nome armazenado no cadastro biométrico existente tem prioridade. Nenhum cadastro é criado, alterado ou refeito pelo inicializador.

## Primeira conversa

No PowerShell, dentro de `C:\Users\jvpmc\Viv`:

```powershell
.\run.bat
```

Aguarde a mensagem `HUD → http://127.0.0.1:8765` e abra esse endereço no navegador. Bata duas palmas, separadas por 120–700 ms, ou use o botão de ativação da HUD. Aguarde a Viv terminar a resposta antes de falar novamente. Há uma janela de 8 segundos para continuar sem palmas; depois disso, ative novamente. Use Ctrl+C no terminal para encerrar.

A HUD VIV 1.2 usa português, esmeralda/dourado, símbolo facetado original e núcleo 3D WebGL leve, com alternativa CSS quando WebGL não está disponível. Alternativa para verificar apenas a HUD: `run_hud_only.bat`.

A aplicação utiliza a configuração existente da chave Gemini. O inicializador não inspeciona, imprime nem cria `.env`; o carregamento que já existia na aplicação continua em tempo de execução. Nunca cole sua chave no terminal de diagnóstico ou nos logs.

## Instalação reproduzível das dependências de voz

Se a `.venv` existente já está funcional, não é necessário reinstalar tudo. Para preparar uma instalação nova, use Python 3.11 e execute as duas instalações nesta ordem:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-viv.txt
.\.venv\Scripts\python.exe -m pip install --no-deps resemblyzer==0.1.4
```

Os arquivos `requirements.txt` e `requirements-viv.txt` seguem a mesma regra: incluem `webrtcvad-wheels==2.0.14` e as dependências de Resemblyzer (`librosa`, `numpy`, `torch`, `scipy`, `typing`); Resemblyzer é instalado separadamente com `--no-deps`. Não execute `pip install resemblyzer` sem essa opção: seus metadados pedem a distribuição `webrtcvad`, enquanto usamos a distribuição substituta `webrtcvad-wheels`. Por essa diferença de nome, `pip check` pode reclamar de `webrtcvad`, mesmo com o módulo funcionando. As dependências transitivas não estão integralmente fixadas em um lockfile.

Para acrescentar somente a voz online ao ambiente existente:

```powershell
.\.venv\Scripts\python.exe -m pip install edge-tts==7.3.1
```

Nenhuma instalação é executada automaticamente ao abrir a Viv. Não são necessários CUDA, Kokoro nem Chromium para conversar.

## Modelos e primeira inicialização

Whisper é carregado uma única vez por processo a partir do cache local. Se o modelo estiver ausente, a inicialização para com uma orientação. Instale explicitamente (com internet):

```powershell
.\.venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"
```

Depois execute `run.bat` novamente. O comando pode baixar arquivos grandes; não é repetido pelo inicializador.

O WebRTC VAD não precisa baixar modelos. O Resemblyzer usa os pesos distribuídos com seu pacote. Se o reconhecimento do proprietário estiver indisponível ou não houver cadastro, a conversa continua, mas ações privilegiadas são recusadas. Combine separadamente qualquer novo cadastro ou recadastro; não execute o script de enrollment como parte deste teste.

A ativação por palavra `hey_jarvis` está desabilitada neste perfil; duas palmas e botão da HUD continuam habilitados. Se decidir reativá-la, instale os pesos explicitamente antes de mudar `wakeword.enabled`:

```powershell
.\.venv\Scripts\python.exe -c "from openwakeword import utils; utils.download_models(['hey_jarvis'])"
```

RAG de documentos, memória vetorial e rotinas proativas ficam desabilitados neste perfil de conversa para não carregar modelos opcionais nem disparar falas agendadas. Histórico em memória, registro SQLite, memória principal existente e verificações de segurança continuam ativos. Nenhum dado existente é apagado.

## Teste automatizado, sem microfone

```powershell
.\.venv\Scripts\python.exe -B scripts/test_conversation.py
```

A suíte usa simulações de STT, Gemini, TTS e ferramentas. Não lê `.env`, não abre o microfone, não faz chamadas externas e não executa ações no Windows. Verifica contexto, identidade, limite de histórico, confirmações negativas, proteção biométrica, confirmação de ações destrutivas, palmas, limpeza de áudio antigo, ativação manual, reutilização do Whisper, conversão do histórico para Gemini, seleção da voz, recuperação de falhas e entrega dos eventos à HUD entre threads.

## Teste real para você executar

1. Inicie com `run.bat` e abra a HUD.
2. Ative por duas palmas e diga: “Olá, Viv. Vamos imaginar uma viagem para Curitiba.”
3. Espere terminar a resposta e pergunte: “Qual cidade eu acabei de mencionar?” A resposta deve ser Curitiba.
4. Espere mais de 8 segundos, use o botão da HUD e pergunte: “Qual é o seu nome?” A resposta deve ser Viv, em português, com voz feminina.
5. Faça mais dois turnos: o Whisper não deve ser carregado novamente. Acompanhe transcrição, estados e resposta na HUD.
6. Encerre com Ctrl+C. Não teste desligamento, exclusão, shell ou controle do computador nesta validação.

Se não houver captura, confirme `audio.input_device_name` e `audio.input_hostapi` em `config.yaml`; a Viv resolve o nome a cada início, pois índices mudam ao conectar dispositivos. Se as palmas não forem detectadas, use o botão da HUD e ajuste posição/volume antes de mudar limiares.

## Limitações desta etapa

- Gemini recebe texto/contexto; Edge TTS recebe o texto a ser falado. Ambos precisam de internet. Whisper e captura de áudio são locais.
- Gemini atualmente devolve a resposta completa antes da síntese; não há streaming real de tokens da API.
- A conversa é por turnos. Não há interrupção confiável por palmas enquanto a Viv fala; áudio capturado durante processamento/reprodução é descartado. Aguarde o fim da resposta para falar. Não há cancelamento acústico de eco.
- O contexto automático cobre até 12 turnos anteriores na mesma execução. O registro SQLite persiste, mas não é recarregado automaticamente como histórico após reiniciar.
- A detecção de palmas usa uma heurística de intensidade e transientes; o desempenho depende do ambiente.
- A suíte simulada não comprova a qualidade do microfone, a latência real, a reprodução MP3 nem a disponibilidade dos serviços. O teste real acima confirma essas partes.

## Viv 1.1: busca confiável e compatibilidade

A combinação validada é `duckduckgo-search==7.2.1` + `primp==2.0.1`. O adaptador em `core/web_search.py` restringe a escolha do perfil a `chrome_146`, aceito pelo `primp` instalado. A lista padrão antiga do DDGS contém `firefox_128`, que não é aceito. Nenhum arquivo da `.venv` foi editado. Ao atualizar qualquer dessas duas bibliotecas, revalide a construção do cliente, os parâmetros e o teste real: `_impersonates` é um detalhe interno da versão 7.2.1.

A verificação TLS permanece ativa nos dois provedores. Quando DuckDuckGo não retorna resultados ou limita o acesso, a Viv tenta uma consulta pública no RSS do Bing. Não usa credenciais, não resolve desafios e não tenta contornar bloqueios. Se ambos falharem, retorna uma falha clara. A consulta é enviada aos provedores usados; não inclua informações privadas em pesquisas públicas.

```powershell
.\.venv\Scripts\python.exe -B scripts/test_search_live.py
```

Esse teste usa uma consulta fixa sobre a documentação pública do Python. Na validação de 1.1, DuckDuckGo respondeu `202 Ratelimit`; o caminho alternativo retornou três resultados em **920 ms**, incluindo `python.org`. Isso confirma a pesquisa funcional com fallback; não significa que o DuckDuckGo estava disponível naquele momento.

## Como medir a velocidade

1. Execute `run.bat` e abra a HUD. Faça cinco perguntas curtas, esperando cada resposta terminar.
2. Observe o painel **Diagnóstico de latência** após cada turno. A medida principal é **do fim da captura ao início do áudio**, separada do tempo em que você estava falando.
3. Faça uma pergunta que peça pesquisa pública. Compare o tempo de busca, ferramentas e o número de chamadas Gemini.
4. Compare medianas de pelo menos cinco turnos equivalentes, não apenas um resultado de rede. A primeira transcrição pode ter custo de aquecimento.
5. Para resumir os registros locais:

```powershell
.\.venv\Scripts\python.exe -B eval/eval_latency.py
```

O arquivo `data/latency-v1.1.jsonl` contém apenas ID aleatório de turno, horários, durações, contagens, estado e RAM medida. Não contém falas, respostas, argumentos de ferramentas, embeddings ou chaves. Os registros antigos de conversa/auditoria já existentes não foram apagados nem convertidos: o novo diagnóstico é separado deles.

| Campo | Medida |
|---|---|
| `capture_ms` | Captura até silêncio final, incluindo o tempo da sua fala e o VAD |
| `speaker_ms` | Verificação biométrica existente |
| `whisper_ms` | Transcrição completa, incluindo consumo dos segmentos |
| `gemini_ms` | Soma das chamadas Gemini do turno, sem reprodução TTS |
| `tools_ms` | Execução das ferramentas, excluindo espera por confirmação |
| `search_ms` | Busca e eventual fallback; já está incluída em ferramentas |
| `tts_generate_ms` | Rede e geração do áudio Edge TTS |
| `tts_decode_ms` | Decodificação do MP3 em memória |
| `tts_playback_ms` | Inicialização e espera pela reprodução |
| `playback_start_ms` | Da ativação ao retorno da primeira chamada `sd.play` |
| `response_start_ms` | Do fim da captura ao mesmo início de reprodução |
| `total_ms` | Turno inteiro, incluindo fala do usuário, confirmações e reprodução |

Início de reprodução é uma aproximação por software: não mede o instante acústico nos alto-falantes nem a latência interna do driver. Não some campos sobrepostos. Campos ausentes aparecem como `—`, não como zero. Turnos sem fala e falhas também geram diagnóstico. O estado “Gemini conectado” significa que a última chamada da sessão teve sucesso; não é uma promessa de disponibilidade futura.

## Medições realizadas em 1.1

Benchmark sintético, com texto público, sem microfone, sem reprodução e sem usar a chave Gemini:

| Ensaio | Tempo |
|---|---:|
| Edge TTS, duas frases em duas solicitações | 2.815 ms |
| Edge TTS, as mesmas frases em uma solicitação | 1.413 ms |
| Decodificação da resposta única | 1,7 ms |
| Carregamento do Whisper Small em cache | 1.360 ms |
| Primeira transcrição do áudio de 4,512 s | 2.249 ms |
| Segunda transcrição, mesmo modelo em memória | 2.153 ms |

Esses resultados são uma amostra, não um SLA. O custo de síntese caiu aproximadamente 50% nesse ensaio ao agrupar a resposta. A versão 1.1 faz uma síntese por resposta completa, pois o adaptador Gemini atual já entrega o texto completo. Isso reduz viagens de rede e pausas entre frases; não comprova redução de 50% no tempo total da conversa nem no início da primeira frase. O Whisper Small CPU/int8 foi preservado. Gemini, captura real e início acústico da reprodução precisam ser medidos na sua próxima conversa.

Para repetir o benchmark sintético (envia somente duas frases públicas ao Edge TTS; não baixa modelos):

```powershell
.\.venv\Scripts\python.exe -B scripts/benchmark_voice.py
```

## Validação funcional e visual

```powershell
.\.venv\Scripts\python.exe -B scripts/test_conversation.py
.\.venv\Scripts\python.exe -B scripts/test_hud.py
```

A suíte de conversa usa simulações e inclui busca, TLS, métricas sem conteúdo, contexto, duas palmas, bloqueios e confirmações. O teste da HUD usa Edge headless instalado, servidor local que serve somente `web/` e endpoints simulados; não inicia a Viv real. Verifica ativação, confirmação/recusa, estados, auditoria, conexão Gemini, renderização de texto e layout móvel. As imagens em `artifacts/viv-1.1` são capturas de teste com dados fictícios, não medições de RAM da sessão real.

A HUD não depende de Three.js, fontes remotas ou scripts externos. A auditoria só é consultada quando aberta, com intervalo de 10 s; estado e RAM são atualizados a cada 5 s. Animações respeitam a preferência de movimento reduzido. O avatar ainda é um espaço reservado, sem modelo facial implementado.

## Viv 1.2 — pesquisa, escuta e presença

### Diagnóstico do episódio Transformers

A auditoria existente mostrou uma transcrição com “transformos”, recuperada como “Transformers” na resposta. Nas duas primeiras interações não houve chamada de busca registrada, apesar das promessas. Depois, as consultas enviadas mantinham `primeiro`, `Prime` e `Transformers`; os resultados retornados eram páginas sobre números ordinais. Portanto, o problema principal foi aceitar resultados irrelevantes e prometer ações sem executá-las, não remover Transformers dos argumentos.

A investigação leu somente o trecho pertinente da auditoria e os registros de memória correspondentes. O `.env` não foi lido. O cadastro biométrico e as regras de autorização não foram alterados.

### Novo fluxo de pesquisa

- Pedidos explícitos de pesquisa passam pela ferramenta registrada antes da resposta. O mesmo acontece quando o modelo gera uma promessa de pesquisar, sem falar a promessa ao usuário antes da execução. Negativas como “não pesquise” são respeitadas.
- A consulta original é preservada. Em referências como “pesquisa mais sobre ele”, são recuperados a pergunta anterior relevante e nomes apresentados na resposta anterior, sem enviar todo o histórico à busca.
- Gemini pode planejar até duas reformulações, em português ou inglês, recebendo apenas a pergunta contextualizada. O código rejeita consultas que removam os termos protegidos; se o planejamento falhar, usa reformulações locais conservadoras. A correção `transformos` → `Transformers` só se aplica quando `Prime` aparece junto.
- No máximo **três consultas por turno**. Repetir a chamada no mesmo turno reutiliza o relatório; não cria novas tentativas sem limite.
- O filtro exige termos do assunto nos títulos/trechos, URLs HTTP(S) válidas e indícios de prioridade/origem quando a pergunta contém “primeiro”. Páginas apenas sobre ordinais são rejeitadas.
- A HUD distingue pesquisa iniciada, resultados recebidos, relevantes, concluída, sem resultados relevantes e erro da ferramenta. Os links são obtidos diretamente dos resultados aceitos, não de URLs inventadas pelo Gemini.
- Sem evidência relevante, a resposta é determinística e honesta: não confirma o fato nem diz que encontrou fontes. Com evidências, o Gemini recebe trechos identificados como dados não confiáveis e deve responder em português, reconhecendo ambiguidades.

**Limite importante:** a validação local é lexical e conservadora, não uma prova semântica ou factual. Nomes homônimos, universos alternativos e perguntas com referências ambíguas podem exigir esclarecimento. Trechos de busca não equivalem à leitura integral da fonte. A qualidade dos provedores públicos continua variável.

Na consulta pública de validação sobre o primeiro Prime, uma reformulação inicialmente encontrou uma página genérica sobre Transformers. O filtro final, mais estrito, rejeitou essa página por não trazer evidência suficiente sobre o primeiro Prime e terminou com **sem resultados relevantes** após três tentativas. Isso valida a rejeição honesta; **não valida uma resposta factual ao caso específico**. A chamada real do planejador Gemini não foi testada usando sua chave. Uma tentativa diagnóstica na API pública da Wikipédia recebeu HTTP 403 e não foi adicionada ao fluxo de produção.

### Privacidade do diagnóstico

Eventos novos de pesquisa contêm apenas estados, número de tentativas e contagens. O evento de conclusão inclui títulos e links das fontes para exibição na HUD, sem texto da pergunta ou argumentos de consulta. Novos eventos `user_turn` da auditoria guardam apenas o tamanho da fala; eventos de busca não persistem seus argumentos/resultados brutos. O texto das conversas continua na memória existente, conforme o funcionamento anterior. Os registros antigos não foram apagados. O painel de fontes pode mostrar o assunto pesquisado, então continua sendo uma interface pessoal.

### Escuta e sensibilidade

A abertura automática de um novo turno exige VAD positivo, energia acima do ruído estimado e pelo menos 160 ms de fala contínua. A gravação precisa acumular 200 ms de voz; 240 ms de pré-captura ajudam a preservar o início de palavras curtas. Após 4 segundos sem fala válida, não envia áudio vazio ao Whisper. Duas palmas continuam funcionando, mas um único ruído forte sustentado não conta como duas palmas.

O seletor da HUD oferece **Baixa** para locais ruidosos, **Normal** para uso geral e **Alta** para voz baixa/distante. O ajuste vale para a sessão; para persistir, use `audio.sensitivity` em `config.yaml`. Isso muda o limiar de detecção, não o ganho do dispositivo no Windows nem a biometria. O nível do microfone não sobe artificialmente durante a reprodução TTS.

Dormindo significa que a janela de continuação acabou: duas palmas ou botão continuam disponíveis. Em espera corresponde à janela para continuar a conversa. Erros ficam visíveis até nova ativação. Televisão, música com voz e outras pessoas ainda podem passar pelo VAD: ele não substitui reconhecimento de proprietário nem cancelamento acústico de eco. Fale depois que a Viv terminar.

### Voz e visual

Francisca continua feminina em português: `rate: '-5%'`, `pitch: '+3Hz'`, `volume: '-3%'`. Esses parâmetros foram aceitos pelo serviço e decodificados em memória em teste real, sem reprodução. Usamos os controles suportados de `edge_tts.Communicate`, não SSML arbitrário. O texto é orientado para gentileza, delicadeza e elegância, sem infantilização ou intimidade presumida. A preferência auditiva deve ser validada por você.

O núcleo WebGL usa 768 triângulos, até 30 quadros/s, densidade de pixels limitada e pausa quando a página está oculta. Não baixa bibliotecas. O símbolo dourado facetado é original, inspirado na referência visual, sem reproduzir uma personagem. Há alternativa CSS para ausência de WebGL e preferência de movimento reduzido. O avatar feminino permanece reservado para uma etapa futura.

### Testar a versão 1.2

Inicie com `run.bat`, abra a HUD e recarregue a página para receber os novos arquivos. Se uma instância antiga estiver aberta, encerre-a com Ctrl+C antes de iniciar outra.

1. Use duas palmas e diga “Pesquise quem foi Prima nos Transformers”. A HUD deve passar por Pesquisando e mostrar fontes reais ou informar ausência de evidências, sem prometer uma tentativa que não executou.
2. Diga “Agora pesquisa mais sobre ele”. O assunto deve ser preservado; a ferramenta não deve receber só “ele” ou “primeiro”.
3. Teste “Quem foi o primeiro presidente do Brasil?” e “Qual a diferença entre Optimus Prime e Prima?”. Quando a busca for solicitada explicitamente, sua execução é obrigatória; perguntas gerais podem ser respondidas sem pesquisa, mas a Viv não deve fingir que pesquisou.
4. Faça barulho leve sem falar durante a janela de continuação. Ajuste a sensibilidade se necessário. Compare também voz baixa e respostas curtas.
5. Verifique os estados Dormindo, Em espera, Ouvindo, Processando, Pesquisando, Falando, Erro e Sem conexão/ferramenta indisponível. O estado de confirmação existente permanece separado.

Testes sem microfone nem controle do computador:

```powershell
.\.venv\Scripts\python.exe -B scripts/test_conversation.py
.\.venv\Scripts\python.exe -B scripts/test_research.py
.\.venv\Scripts\python.exe -B scripts/test_audio_gates.py
.\.venv\Scripts\python.exe -B scripts/test_hud.py
```

Testes externos opcionais, com perguntas/frase públicas fixas e sem usar a chave Gemini:

```powershell
.\.venv\Scripts\python.exe -B scripts/test_research_live.py
.\.venv\Scripts\python.exe -B scripts/test_voice_style.py
```

O teste de pesquisa real diferencia ausência honesta de evidência de falha de ferramenta. Não considera que a pergunta foi respondida quando não há fontes. O teste de voz apenas gera/decodifica áudio em memória. O teste visual usa endpoints simulados e captura os estados em `artifacts/viv-1.2/`; valores de RAM dessas capturas são fictícios.


### Correção de escuta e painel de presença

A captura após ativação agora usa WebRTC com proteção apenas contra silêncio digital,
aceita interrupções curtas na fala e aguarda até 8 segundos para começar. O filtro mais
restritivo permanece na ativação automática de continuação. Biometria e permissões não
foram alteradas. O microfone Realtek é selecionado pelo nome e pela interface MME, sem alterar controles do Windows.
Falha de abertura ou falta de quadros aparece como erro; reinicie a Viv após conferir
se o dispositivo de entrada é o correto. A HUD exibe quadros de fala e pico RMS/dBFS,
sem armazenar áudio ou transcrição nesses diagnósticos.

Gemini é verificado uma vez ao iniciar e pelo botão **Verificar conexão**. A verificação
usa `models.get`, com autenticação, timeout de 10 s e TLS, sem conversa ou ferramentas:
https://ai.google.dev/api/models#method:-models.get . Isso verifica acesso ao modelo;
não comprova disponibilidade de cota de geração. **Última chamada OK** aparece somente
após uma chamada de conversa bem-sucedida. Nenhuma chave aparece no diagnóstico.

O painel tem sistema à esquerda, núcleo orgânico central e conversa à direita, com
marca triangular esmeralda/dourado/prata, animação de escuta independente do volume,
WebGL limitado a 30 fps e suporte a movimento reduzido. Os controles, fontes, tempos,
confirmações e auditoria continuam disponíveis, inclusive em telas pequenas.

Testes adicionais: `scripts/test_audio_gates.py` cobre fala baixa com pausas, transientes,
falta de quadros, verificação Gemini simulada e saúde do microfone. `scripts/test_voice_style.py`
usa uma frase pública da Francisca, atenua em memória e passa pelo WebRTC real; as etapas
Whisper/Gemini/TTS seguintes são simuladas. Não abre microfone nem reproduz áudio.

Para experimentar: encerre a instância anterior com Ctrl+C, execute `.\run.bat` nesta
pasta e atualize http://127.0.0.1:8765 com Ctrl+F5. Clique **ATIVAR VIV**, aguarde
**Ouvindo** e diga uma frase. Confira o medidor, os quadros de fala, a transcrição e
as durações Whisper/Gemini/TTS. O teste físico de microfone e a resposta Gemini com sua
configuração devem ser confirmados nessa sessão; os testes automatizados não usam sua chave.


### Realtek por nome e ativação ao chamar Viv

Diagnóstico de 15/10/2026: o índice 1 passou a ser **Wireless Controller**, enquanto o
**Microfone (Realtek(R) Audio)** estava no índice 2 (MME). O sinal de -86 dBFS vinha da
entrada errada. A seleção agora usa `audio.input_device_name` e `audio.input_hostapi`.
O índice é resolvido em cada inicialização; se não houver correspondência única, a Viv
informa erro e não troca silenciosamente de microfone. A HUD mostra o nome real.

`wakeword.voice_name_enabled: true` permite dizer **Ei, Viv** ou **Viv, me explique as
estrelas**. Não ativa o modelo legado hey_jarvis nem baixa modelos. Reutiliza Whisper Small
CPU/int8 depois de detectar fala. A análise do nome ocorre localmente, sem eventos contendo
transcrições, sem gravar conversa ambiente e sem chamar Gemini para falas não dirigidas à Viv.
Uma menção no meio da frase não ativa. A variante que Whisper escreve como “vive” é aceita
somente como vocativo (com saudação, pontuação ou isolada). Possíveis falsos positivos de
reconhecimento não concedem autorização: a biometria e as confirmações continuam valendo.

Ao chamar apenas o nome, aguarde **Ouvindo** e faça o pedido. Nos testes sintéticos o
reconhecimento local levou 2,8–3 s, além do fim da fala/VAD. O detector reutiliza o modelo
existente, mas custa CPU durante fala ambiente e não oferece interrupção durante a resposta.
O botão e as duas palmas continuam como alternativas. Para desabilitar a chamada por voz,
use `wakeword.voice_name_enabled: false` e reinicie.

Testes: `scripts/test_voice_wake.py` (7 verificações simuladas de seleção, nome, descarte
local e segurança); `scripts/test_voice_wake_live.py` (três frases públicas via Edge TTS,
Whisper real em memória, sem microfone, reprodução ou Gemini). A seleção Realtek e o formato
16 kHz foram consultados sem abrir a captura. A confirmação da entrada física requer falar
com a Viv após reiniciar `run.bat` e atualizar a HUD com Ctrl+F5.

O estado saiu da faixa superior e passou a flutuar abaixo do núcleo, com cores por estado.
O botão de ativação não tem seta. O efeito respeita a preferência de movimento reduzido.


### Revisão: ações, ativação e núcleo 2D

A HUD deixou de carregar WebGL: a marca triangular aparece em SVG, com dois anéis 2D.
Os estados são texto e cor, sem faixa de fundo nem cartão de erro no centro.

Os registros analisados mostraram falhas Gemini antes de qualquer solicitação de ferramenta,
e análises de nome de 33–40 s. O erro HTTP antigo não foi preservado, portanto não é possível
atribuir retroativamente esses erros a cota, autenticação ou formato. Agora a HUD distingue
essas categorias sem mostrar corpo de resposta, chave ou conteúdo privado. A integração
omite parâmetros vazios de ferramentas sem argumentos, preserva o conteúdo assinado do
modelo no retorno das ferramentas e responde explicitamente a chamadas paralelas não executadas.
Referência: https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures .
A conversa mostra falha atual em vez de deixar uma resposta antiga parecer resultado do pedido.

O detector do nome usa um único trabalhador local em segundo plano; não acumula trabalhos.
Palmas e botão continuam sendo verificados enquanto a inferência do nome está pendente.
A geração do Whisper para a chamada foi limitada a 48 tokens e uma temperatura, para evitar
repetições e múltiplas tentativas de decodificação. Texto que atinge esse limite é descartado,
sem executar um pedido possivelmente truncado: para pedidos longos, diga “Ei, Viv”, aguarde
“Ouvindo” e só então faça o pedido. A captura/VAD e o processamento de respostas ainda são
por turnos; isso não implementa interrupção da voz durante a reprodução.

A ativação tolera pequenos intervalos de VAD. O detector de palmas aceita transientes de menor
amplitude e reserva a janela da segunda palma antes de iniciar captura de fala. Ajuste
Sensibilidade na HUD se o ambiente for ruidoso. Esses testes não garantem reconhecimento de
toda voz/distância nem ausência de falsos positivos.

`system.kill` agora procura nome exato. “Minecraft” reconhece Bedrock e marcadores de clientes
Java/Fabric/Forge; não encerra todos os processos Java, nem servidores ou launchers por prefixo.
Verifica término e relata ausência/falha sem afirmar sucesso. Continua exigindo biometria e
confirmação. Clientes personalizados sem esses marcadores podem não ser identificados.
A barreira do registro também recusa ferramentas protegidas quando não existe verificador.

Validação: 72 testes Python (conversa, áudio, ativação, ações e pesquisa), HUD desktop/mobile
e três frases públicas com Whisper real. Reconhecimento sintético: 2,37–2,64 s nesta execução.
Nenhum programa real foi encerrado; não foi usado microfone nem lido `.env`. A chamada Gemini
com sua configuração e o reconhecimento físico de palmas/voz requerem teste na sessão real.

Reinicie `.\run.bat` e atualize a HUD com Ctrl+F5. Teste botão, “Ei, Viv” e duas palmas
separadamente. Para fechar Minecraft, salve seu jogo, faça o pedido e confirme somente se a
HUD mostrar a ferramenta e o alvo corretos. Se Gemini falhar, observe a categoria exibida
no painel Sistema; “acesso ao modelo verificado” não comprova cota de geração disponível.


### Modo local enquanto a cota Gemini estiver indisponível

`assistant.local_mode: true` responde a comandos explícitos sem geração Gemini. Quando
quiser voltar à conversa livre, altere para `false` e reinicie. A verificação automática
Gemini também fica suspensa neste modo; o botão de verificação continua opcional.
Edge TTS e pesquisa ainda precisam de internet. Nenhum modelo adicional foi instalado.

Comandos em português atualmente implementados:

- “Ei, Viv, tá me ouvindo?”; “Que horas são?”; “O que você pode fazer?”
- “Pesquise sobre Optimus Prime”: consulta real e links na HUD; sem resumo gerado pelo Gemini.
- “Me lembre em cinco minutos de beber água”; “Liste meus lembretes”.
- “Abra a calculadora”, “Abra o bloco de notas”, “Abra o explorador de arquivos”.
- “Feche o Minecraft”: proprietário verificado e confirmação continuam obrigatórios.
- `Abra o arquivo "C:\caminho\notas.txt"`.
- `Acrescente "Texto novo" ao arquivo "C:\caminho\notas.txt"`: arquivo de texto UTF-8
  `.txt`/`.md`, caminho absoluto, confirmação e biometria; preserva o conteúdo anterior.
  Caminhos de arquivos por voz exigem reconhecimento exato, inclusive o formato entre aspas.
- “Otimize meu PC”: retorna somente diagnóstico de uso, sem alterar configurações.
- “Observe minha tela” ou “Leia minha tela”: lê nomes acessíveis da janela ativa pelo Windows, sem imagem ou Gemini.

Esses comandos não substituem interpretação geral de linguagem natural nem edição arbitrária
de documentos. Pedidos fora dos padrões são recusados claramente e registrados por categoria.
Interpretação de imagens e conversa livre continuam dependentes de um modelo disponível. O modelo não garante
que toda ação de computador seja possível ou segura.

Lembretes são independentes de `proactive.enabled`: `reminders.enabled: true` habilita seu
agendador sem ativar as rotinas prontas antigas. São persistidos em `data/jobs.json`, entregues
à HUD e à fila de voz quando possível. **A Viv precisa permanecer aberta**; lembretes vencidos
são entregues após a próxima inicialização. Não há despertar do computador ou notificação com
o aplicativo fechado. Falha de entrega à fila mantém o lembrete pendente. A fala depende do
Edge TTS; se falhar, o lembrete permanece visível na HUD.

### Testar microfone e transcrição isoladamente

Marque **Testar só transcrição** no painel Sistema antes de ativar. Clique ATIVAR VIV e diga
uma frase curta; compare o texto exibido com o que falou. O próximo turno não chama Gemini,
não verifica biometria, não executa ferramentas e não entra na memória da conversa. Desmarque
para voltar aos comandos. A escolha vale para o turno iniciado após a mudança. Ela não cancela
uma ação já iniciada antes de marcar a opção. Lembretes pendentes continuam sendo entregues.

Compare a mesma frase em três tentativas, em ambiente quieto, mantendo distância do microfone.
O teste informa o que Whisper recebeu/transcreveu; não permite concluir automaticamente se um
erro veio do microfone, do VAD ou do modelo. O relato ditado neste chat usa outro caminho.

### Pendências e pronúncias

`data/capability_gaps.json` reúne ocorrências por categoria; `VIV_PENDENCIAS.md` é o relatório
legível. Não registra transcrições, caminhos nem conteúdo de arquivos. Distingue pedido não
compreendido, visão indisponível, otimização não implementada, falha de ferramenta e cota.
Não marcar automaticamente como resolvido: uma próxima solicitação bem-sucedida não demonstra
que a causa de todas as ocorrências foi eliminada. Após validar uma correção, o relatório
estruturado pode ser atualizado em uma sessão de desenvolvimento.

Pergunte “quais são suas pendências?” ou consulte **Limitações registradas** na HUD. Ao iniciar,
a Viv informa se há pendências. `AGENTS.md` orienta as próximas sessões de desenvolvimento a
consultar o relatório. O texto é diagnóstico, nunca instrução para executar ações.

`wakeword.aliases: [Viv, Vivi, Vive]` aceita variantes de pronúncia; a marca continua VIV.
“Ei, Vive” e “Ei, Vivi” são aceitos sem mostrar esses apelidos na interface. A variante
“vive” continua restrita a um vocativo para não ativar só porque o verbo apareceu numa frase.

A marca SVG se separa em três peças durante processamento, gira lentamente durante pesquisa,
faz um movimento discreto em espera e reduz brilho dormindo. Fala/escuta respondem ao áudio.
Erro usa coral; indisponibilidade usa tom frio; conclusão local confirmada recebe um realce
verde breve. A preferência de movimento reduzido elimina as animações.

Validação desta etapa: testes de comandos locais, persistência de lembretes e pendências,
segurança e UI; nenhuma ação real no Windows foi executada. A consulta pública de teste
retornou três URLs via Bing RSS em cerca de 2 s, sem Gemini. Testes de arquivos usam apenas
pastas temporárias. Iniciar: `.\run.bat`, depois Ctrl+F5 na HUD.


### Complemento local: tela, arquivos e diagnóstico

Sem consumir Gemini, após verificar a voz proprietária:

- “Leia minha tela”: consulta por até 8 segundos os nomes de controles visíveis da janela
  ativa (limites: 200 controles, 60 textos, 5000 caracteres). Não executa instruções que
  apareçam nessa janela. Não lê campos de senha; bloqueia janelas identificadas como `.env`.
  Acessibilidade não é OCR: jogos, imagens, PDFs e alguns editores podem expor pouco texto.
  Coloque a janela desejada em primeiro plano antes de pedir. O resultado aparece somente
  na HUD; no modo local seu conteúdo não entra na memória nem no Edge TTS.
- `Leia o arquivo "C:\Temp\nota.txt"`: leitura UTF-8 limitada a 6000 caracteres na HUD.
- `Crie o arquivo "C:\Temp\nota.txt" com texto "Olá"`: confirmação obrigatória;
  exige pasta existente e recusa sobrescrever arquivo existente.
- `Substitua "antigo" por "novo" no arquivo "C:\Temp\nota.txt"`: confirmação obrigatória,
  trecho exato com uma única ocorrência e backup exclusivo ao lado do original, com sufixo
  `.viv-backup-...`. Não edite simultaneamente em outro programa. Uma interrupção durante
  a escrita pode exigir recuperação manual pelo backup. Backups contêm o conteúdo original.
- “Diagnóstico do PC” / “Otimize meu PC”: uso de RAM/disco e cinco processos com maior RAM,
  com sugestões conforme a amostra. Não encerra processos, limpa arquivos, altera serviços
  ou configurações. Para fechar um aplicativo específico, peça separadamente e confirme.

Edição limitada a `.txt` e `.md`, até 2 MB, com texto novo até 100 KB. Arquivos ocultos e
`.env` são recusados. Não há edição de Word/PDF nem navegação visual autônoma. Caminhos e
aspas por voz continuam exigindo transcrição exata; pedidos que não correspondem ao padrão
não são executados. As verificações biométricas existentes permanecem obrigatórias.

O diagnóstico do microfone agora mostra aviso de sinal muito baixo ou possível saturação,
sem alterar o ganho do Windows. Use “Testar só transcrição” e compare frases curtas em três
repetições. Isso ajuda a investigar; não certifica sozinho o microfone ou a precisão do Whisper.

Testes seguros adicionais: ` .\.venv\Scripts\python.exe -B scripts/test_local_capabilities.py`.
Leitura real de janela e qualidade do microfone precisam ser conferidas pelo usuário;
os testes automatizados usam janela/processos simulados e arquivos temporários.


### Dicas, sem lembretes automáticos de demonstração

As antigas mensagens prontas do JARVIS agora aparecem como dicas em português na HUD,
abaixo da conversa. Não são faladas e não agendam ações. As cópias diárias exatas dessas
mensagens, já persistidas, ficam inativas e fora da lista de lembretes; os registros são
preservados. Lembretes pessoais, inclusive em inglês, continuam funcionando. O cadastro
repetido da mesma rotina diária no mesmo horário não cria novas cópias. Reinicie a Viv
para esvaziar mensagens antigas que já tenham entrado na fila da sessão anterior.


### Interromper a fala e preservar o início do comando

`audio.barge_in_enabled: true` permite interromper a reprodução ao detectar cerca de
240 ms consecutivos de fala pelo VAD e limiar de energia. A escuta ocorre em um monitor
separado durante a reprodução; o áudio inicial é preservado para o turno seguinte,
que passa pela transcrição e biometria normais. Confirmações sensíveis continuam com
seu fluxo próprio; uma interrupção não aprova uma ação. Não interrompe uma ferramenta
que já esteja executando, nem promete cancelar uma solicitação Gemini em andamento.

O pré-áudio de captura passou a 600 ms. A ativação por nome não descarta mais a fila
logo após reconhecer o nome isolado. Whisper Small CPU/int8 foi preservado. Não há
inferência de ação a partir de fragmentos como “a calculadora”.

Teste com fones: reinicie com `.\run.bat`, marque “Testar só transcrição”, ative pelo
botão e diga “Abra a calculadora” três vezes, conferindo se o verbo aparece. Desmarque
a opção, peça “O que você pode fazer?” e, enquanto a Viv responde, diga “Que horas são?”.
Ela deve parar a reprodução, escutar e responder ao novo pedido. Só depois teste ações.
Sem cancelamento acústico de eco, caixas de som podem causar falsas interrupções.
Ajuste a sensibilidade na HUD ou desative `barge_in_enabled` nesse cenário. Não foram
feitos testes físicos de microfone ou reprodução durante o desenvolvimento.


### Recupera??o ap?s restaura??o do Windows (16/10/2026)

JavaScript recuperado dos objetos Git; controles usam as rotas reais de `server.py`.
Refer?ncia do PCM reproduzido agora filtra eco antes de o ?udio chegar ao VAD, Whisper
ou barge-in. A interrup??o por voz e pelo bot?o permanece dispon?vel. N?o ? um AEC
completo: confira com seu microfone e alto-falantes; use fones se persistir retorno.
Reinicie a Viv e atualize a HUD com Ctrl+F5. Detalhes e valida??o:
`artifacts/recuperacao-viv-2026-10-16.md`.


### Encerramento nativo na inicializa??o

O lan?ador usa UTF-8, sa?da sem buffering e faulthandler. Qualquer c?digo diferente
 de zero, inclusive falhas nativas do Windows, aparece no terminal. O arquivo
`data/native-crash.log` cont?m apenas etapas fixas e stacks de falha (sem vari?veis
locais, transcri??es ou credenciais). Ele ? acrescentado, n?o sobrescrito.
Em 16/10 foram encontrados eventos Windows 0xc0000005 em python.exe/ntdll.dll.
Testes isolados de servidor, modelos, VAD, entrada/sa?da silenciosa e s?ntese p?blica
n?o reproduziram a queda. A causa nativa ainda requer o stack da pr?xima ocorr?ncia;
n?o houve substitui??o de depend?ncias ou altera??o de seguran?a do Windows.


### Queda ao interromper a voz: corre??o de 16/10

O stack de `data/native-crash.log` localizou access violation em `sounddevice.stop`,
chamado pelo monitor de barge-in enquanto a thread de reprodu??o finalizava o ?udio.
A reprodu??o agora usa um OutputStream expl?cito, com blocos de 20 ms. Somente a
thread que abre o stream escreve, para, aborta e fecha esse stream. `TTS.stop()`
apenas sinaliza cancelamento; n?o chama mais o driver de outra thread. A lat?ncia
real da interrup??o tamb?m depende do buffer/driver, n?o apenas dos 20 ms.

Valida??o: 62 testes automatizados, HUD e 20 interrup??es de reprodu??o silenciosa
no driver real, em processo isolado, sem microfone. Isso n?o equivale a uma sess?o
longa de conversa real. Reinicie a Viv, teste uma resposta curta e interrompa com
?Que horas s?o??. O registro nativo anterior foi preservado.

A marca central volta a variar as cores por estado por meio dos gradientes, mantendo
as tr?s faces e o movimento dos an?is. Atualize a HUD com Ctrl+F5.


## Cadastrar a voz do proprietario (apos a restauracao)

Pare a Viv com Ctrl+C antes de gravar. No PowerShell em C:\Users\jvpmc\Viv:

```powershell
.\.venv\Scripts\python.exe scripts\enroll_voice.py
```

Informe seu nome e leia as oito frases em portugues no seu tom normal, usando o microfone configurado em config.yaml. Enter inicia cada gravacao de cinco segundos. O script nao executa comandos, nao chama Gemini e nao le .env. Sinais silenciosos, curtos ou saturados sao recusados. A gravacao bruta nao e salva; o cadastro grava o embedding local em data/voiceprint.json.

Se houver cadastro, e necessario digitar SUBSTITUIR para refaze-lo; uma copia com data/hora e preservada. Cancelar nao altera o cadastro. Os limiares de verificacao nao sao reduzidos. Reinicie com .\run.bat para carregar a voz cadastrada. Uma frase isolada muito curta pode nao bastar para verificar a voz; o cadastro nao garante reconhecimento perfeito.
