# Roteiro de validação da Viv

Estes passos dependem da sua voz, do seu microfone e das suas caixas, então só você pode fazê-los. Levam uns dez minutos. Anote o que falhar e em qual passo.

## Antes de começar

1. Abra `run.bat`. A janela da HUD deve abrir com o orbe em "Dormindo".
2. Confira no canto superior direito se o microfone mostrado é o que você usa. Se não for, ajuste `audio.input_device_name` no `config.yaml` e reinicie.

## 1. Ativação

Faça cada uma e confira se o orbe muda para "Ouvindo" e toca um som curto. Entre uma e outra, ponha a Viv para dormir com `Ctrl+Alt+V`.

- [ ] Botão **Ativar Viv**
- [ ] Atalho `Ctrl+Alt+V`
- [ ] Duas palmas
- [ ] "Ei, Viv" (este é o gatilho menos confiável; teste três vezes)

## 2. Conversa

- [ ] Pergunte "que dia é hoje?". Ela deve responder em menos de dois segundos.
- [ ] Faça uma pergunta de seguimento sem repetir o nome ("e amanhã?").
- [ ] Peça algo longo ("me conta a história do Brasil") e fale por cima no meio. Ela deve parar de falar.

## 3. Eco (o teste mais importante)

Com as caixas de som no volume de costume e sem fones:

- [ ] Peça uma resposta longa e fique em silêncio. A Viv deve falar até o fim, sem se cortar.

Se ela se corta sozinha, aumente `audio.barge_in_rms` para `0.12` e repita. Se você não consegue interrompê-la no passo 2, diminua para `0.05`. Com fones, use `audio.headphones: true`.

## 4. Ações no PC

- [ ] "Abre o bloco de notas."
- [ ] "Coloca o volume em trinta."
- [ ] "O que tem na minha tela?"
- [ ] "Pesquisa a previsão do tempo para amanhã." (um cartão com as fontes deve aparecer)
- [ ] "Me lembra de levantar em um minuto." (ela deve avisar depois de um minuto, mesmo dormindo)

## 5. Ação perigosa

Crie um arquivo qualquer na área de trabalho, por exemplo `teste.txt`.

- [ ] Peça "apaga o arquivo teste.txt da área de trabalho". A Viv deve pedir confirmação e um cartão deve aparecer. O arquivo ainda existe.
- [ ] Clique em **Não**. O arquivo continua lá.
- [ ] Peça de novo e clique em **Sim**. O arquivo some.

Depois do cadastro de voz (`.venv\Scripts\python.exe scripts\enroll_voice.py`, com a Viv fechada):

- [ ] Peça para apagar outro arquivo e diga "sim". Deve executar.
- [ ] Peça de novo e deixe outra pessoa dizer "sim". Não deve executar; o cartão avisa "Voz não reconhecida".

## 6. Sono

- [ ] Diga "tchau, Viv". Ela se despede e dorme.
- [ ] Acorde, fique 60 segundos em silêncio. Ela dorme sozinha.

## O que já foi verificado sem você

- 142 testes automáticos passam.
- Sessão real com a sua chave: voz em português, ferramenta `system_status`, Bloco de Notas aberto por pedido em texto.
- Ação perigosa real (`fs_delete` de um arquivo temporário): ficou pendente e só executou depois do clique.
- Uma fala de nove segundos pelas caixas deste PC não se autointerrompeu com o limiar padrão.

## O que não foi verificado

- Nenhum pedido feito por voz de verdade.
- "Ei, Viv" e palmas com som real.
- Biometria (não há cadastro neste PC).
- Interrupção por voz.
- Navegador (Playwright) e análise de tela numa sessão real.
