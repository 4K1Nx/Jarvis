# Selecao economica Gemini e estado da HUD

Causa observada: servidor local estava acessivel e microfone ativo; ultima chamada Gemini havia expirado. A desconexao WebSocket informada nao foi reproduzida durante a consulta. Nao foi comprovada queda do processo nesta rodada.

Implementacao:
- core/model_selection.py: lista curada de modelos de texto em ordem crescente de precos de entrada e saida; cruza catalogo real, testa frase publica sem memoria ou ferramentas e para no primeiro sucesso. Uma tentativa por modelo, timeout de rede de 8 s, orcamento de selecao de 60 s, sem workers duplicados. Catalogo segue limite de tres paginas. Falhas de autenticacao/acesso interrompem os testes. Precos sao referencia de 16/10/2026, nao medicao de cobranca.
- core/llm.py: configuracao de sessao em copia, escolha aplicada no inicio do turno, timeout de requisicao limitado a 30 s, diagnostico limpo antes da chamada, thinking baixo para os modelos Gemini 3 da lista.
- core/orchestrator.py: aplica escolha ao iniciar turno e verifica orcamento de 90 s entre rodadas de ferramentas. Uma requisicao ou ferramenta ja em andamento nao e interrompida por esse limite; nao se trata de cancelamento global de acoes.
- server.py: endpoints reais GET /api/gemini/models e POST /api/gemini/models/select; selecao automatica no inicio; status informa modelo ativo da sessao.
- web/index.html, web/viv.js, web/viv.css: lista/resultados/botao de selecao; fetch de status com timeout; erro HTTP/rede encerra estado visual de processamento; tentativa WebSocket pendente limitada a 8 s e reconexao sem duplicacao.
- scripts/test_model_selection.py, scripts/test_audio_gates.py, scripts/test_hud.py: regressoes de selecao, sessao, endpoints e desconexao.

88 testes passaram e teste de navegador HUD passou sem erros JavaScript, incluindo selecao e perda de conexao. APIs, audio e ferramentas simulados nos testes automatizados. Teste de geracao basica nao certifica visao ou ferramentas do modelo escolhido.

Reiniciar com .\run.bat e atualizar HUD com Ctrl+F5. Ver Sistema > Modelos Gemini para resultados; repetir testes pelo botao quando necessario. Nenhuma mudanca de modelo e gravada em config.yaml por esse seletor; ele opera apenas nesta sessao. Sem mudancas em .env, biometria, modelos locais ou permissoes.

Precos e capacidade: https://ai.google.dev/gemini-api/docs/pricing e https://ai.google.dev/gemini-api/docs/thinking

## Validacao real apos reinicializacao

Selecao concluida: gemini-3-flash-preview respondeu HTTP 200 em 1.407 ms. Tentativas anteriores: gemini-2.5-flash-lite HTTP 404 (656 ms); gemini-3.1-flash-lite tempo esgotado ou conexao (8.000 ms); gemini-2.5-flash HTTP 404 (422 ms). gemini-3.8-flash nao foi testado, pois a busca parou no primeiro sucesso. Estado do microfone: ok. Viv dormindo. Modelo ativo ainda era 3.8 no instante da consulta; a escolha 3 Flash Preview esta pendente para aplicacao no inicio do proximo turno, como previsto. Teste publico de geracao confirmado; conversa completa e ferramentas ainda precisam de validacao manual.
