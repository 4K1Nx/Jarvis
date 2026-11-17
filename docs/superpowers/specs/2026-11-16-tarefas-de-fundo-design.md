# Tarefas de fundo — desenho

Data: 2026-11-16. Frente 4 de 8 do pedido de melhorias da Viv.

## Por quê

Hoje a conversa espera cada ferramenta terminar (`Viv._run_tools` em `viv/live.py` aguarda `gate.submit`).
Ao pedir um slide, a Viv fica muda até o arquivo ficar pronto. O usuário quer que ela continue
conversando, diga como a tarefa está quando perguntada e avise ao terminar, como uma pessoa faria:
termina a frase que estava dizendo e muda de assunto para contar que ficou pronto.

## Objetivos

- Nenhuma função da Viv congela a conversa por mais de alguns segundos.
- Vale para todas as ferramentas, sem marcar uma por uma.
- "Como está o slide?" tem resposta real: etapa atual e tempo decorrido.
- Ao terminar, ela avisa sem cortar a própria fala no meio.
- Ações rápidas continuam instantâneas, com o resultado na mesma resposta, como hoje.

## Fora do escopo

- Cancelar uma tarefa qualquer no meio. Uma função Python em outra thread não pode ser interrompida
  com segurança. Continuam valendo as paradas que já existem (`codigo_parar`, `agente_parar`,
  `tela_parar_vigia`).
- Tarefas que sobrevivem a fechar a Viv.
- Mudar o que as ferramentas fazem. A qualidade do slide é a frente 8.

## O que não pode acontecer

- Uma ação perigosa rodar sem a confirmação de hoje. O portão (`viv/safety.py`) decide antes; só a
  execução já autorizada vai para o fundo.
- A mesma ação rodar duas vezes porque o modelo repetiu a chamada.
- Duas tarefas mexendo ao mesmo tempo no mesmo recurso (o navegador, por exemplo).

## Caminhos considerados

1. **Automático por tempo (escolhido pelo usuário).** A ferramenta começa normal; se passar de um
   limite, vira tarefa de fundo. Cobre tudo sem marcação e mantém o rápido rápido.
2. Marcar as lentas à mão. Previsível, mas qualquer função lenta não marcada volta a travar.
3. Um processo de agente por tarefa, como o agente de código. Pesado demais para uma pesquisa.

O modo "não bloqueante" nativo do Gemini Live foi descartado como base: dependeria do modelo
configurado aceitar, exigiria gastar cota para testar e não resolveria progresso nem duplicatas.
A solução fica toda no programa (decisão minha).

## Como funciona

### `viv/tasks.py` (novo)

Classe `Tasks`, uma por execução da Viv.

- `run(name, args, call) -> str`: executa `call()` (o `registry.call` já autorizado) numa thread e
  espera até `tasks.background_after_seconds` (padrão 4, em `config.yaml`).
  - Terminou a tempo: devolve o resultado. Nada muda em relação a hoje.
  - Não terminou: registra a tarefa e devolve ao modelo um texto do tipo "em segundo plano: tarefa 3
    (Criando apresentação) continua rodando; diga em uma frase que está cuidando disso e siga a
    conversa; o sistema avisa quando terminar; não chame de novo".
- Cada tarefa guarda: número, título (o `describe` da ferramenta), início, última etapa e fração
  (vindas de `registry.progress`), estado (rodando, pronta, falhou) e resultado.
- **Duplicata:** a mesma ferramenta com os mesmos argumentos enquanto roda devolve "já está rodando".
- **Um recurso por vez:** uma trava por módulo de ferramentas (`registry.module_of`). Uma segunda
  chamada ao mesmo módulo espera a vez na própria thread, com o mesmo limite de tempo.
- **Progresso por tarefa:** a thread da tarefa marca qual tarefa é a atual (`contextvars`);
  `registry.progress` atualiza essa tarefa além de emitir o evento da HUD.
- **Fim:** chama `on_done(tarefa)`, ligado em `main.py` ao novo aviso da Viv (abaixo). O texto leva o
  resultado (até 2000 caracteres) e a orientação "conte ao usuário em uma ou duas frases".
- As 20 últimas tarefas terminadas ficam na lista para consulta.

### Portão (`viv/safety.py`)

As duas chamadas diretas a `registry.call` em `Gate.submit` (ação comum e ação autorizada pela voz)
passam por `Tasks.run`. A execução após confirmação por cartão já roda em thread própria e avisa no
fim; ela passa a ser registrada em `Tasks` também, para aparecer no progresso. Sem `Tasks`
configurado (testes antigos), o portão chama direto como hoje.

### Aviso no momento certo (`viv/live.py`)

Hoje os avisos do sistema são enviados ao modelo na hora, mesmo com ela falando. Novo método
`Viv.announce(text)`: o aviso entra numa fila entregue pelo `_watchdog` só quando o áudio dela parou
e o turno fechou (estado ouvindo). Se o usuário estiver falando, espera o turno dele acabar.
Se ela estiver dormindo, acorda para contar (decisão minha: o usuário pediu a tarefa e quer saber do
fim; lembretes já se comportam assim).

Enquanto houver tarefa rodando, o estado volta a "pensando/ouvindo" normalmente; a HUD mostra as
tarefas por um evento novo `tasks`.

### Ferramenta nova: `tarefas_andamento`

Em `viv/tools/assistant.py`. Sem parâmetros. Lista as tarefas rodando (título, etapa, percentual
quando houver, tempo decorrido) e as terminadas há pouco com o resultado resumido. Sem cartão.

### Persona (`viv/persona.py`)

Um parágrafo: tarefa que demora continua em segundo plano; ela diz que está cuidando e segue a
conversa; para saber do andamento usa `tarefas_andamento`; ao receber o aviso de fim, conta o
resultado de forma natural; não repete a chamada.

### HUD (`web/app.js`, `web/viv.css`)

A barra de progresso atual vira uma lista compacta: uma linha por tarefa rodando, com título, etapa
e barra. Some quando a última termina. O layout fino fica para a frente 5 (visual).

## Testes

- `tests/test_tasks.py`: termina a tempo devolve o resultado; estoura o limite devolve "em segundo
  plano" e chama `on_done` depois; duplicata; trava por módulo; progresso atribuído à tarefa certa;
  erro da ferramenta vira tarefa "falhou" com aviso.
- `tests/test_safety.py`: ação perigosa continua exigindo confirmação antes de qualquer execução.
- `tests/test_live.py`: `announce` não é entregue com áudio tocando; é entregue ao fechar o turno;
  acorda a Viv se estiver dormindo.
- Relógio e espera injetados, como nos testes atuais; nada de `sleep` real.

## Fica para quem implementar

Nomes internos, formato exato dos textos devolvidos ao modelo e o desenho da lista na HUD, dentro
do que está acima.
