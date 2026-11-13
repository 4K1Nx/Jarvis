# Diagnostico Gemini

Testes reais realizados pelo endpoint local da Viv, com a credencial mantida apenas no processo existente; nenhum .env foi lido pelo agente.

- GET metadados v1beta/gemini-2.5-flash: HTTP 200.
- Catalogo v1beta: HTTP 200, gemini-2.5-flash ainda listado.
- POST generateContent v1beta, frase publica minima sem memoria/ferramentas: HTTP 404, NOT_FOUND, categoria model_retired.
- POST generateContent v1, mesma frase publica: HTTP 404, NOT_FOUND, categoria model_retired.
- O relato anterior de modelo indisponivel era generico. Agora a origem esta classificada: a geracao informa retirada do modelo, apesar dos metadados acessiveis.

Alterados: core/llm.py (catalogo limitado a tres paginas, fase/HTTP/categoria segura, probe v1); server.py (diagnostico no status/verificacao); web/viv.js (exibe etapa e alternativas do catalogo); scripts/test_gemini_verification.py (regressoes).

Validacao automatizada: 41 testes passaram (Gemini, conversa e recuperacao); HUD passou em oito estados, botoes, confirmacoes, auditoria, renderizacao segura e layout mobile, sem erros JS. Nenhuma acao do Windows, captura de tela ou alteracao de credencial nos testes.

Usuario autorizou Gemini 3.8 Flash. config.yaml atualizado (conversa e identificacao de visao); HUD preserva o nome real do modelo nos eventos.

Testes reais apos a troca: duas verificacoes retornaram HTTP 503 / UNAVAILABLE na geracao (3,28 s e 1,74 s para cada verificacao completa). Metadados retornaram HTTP 200. Nao houve resposta gerada com sucesso nessas duas verificacoes.

Tratamento adicional: no maximo tres chamadas de geracao apenas para HTTP 502/503/504, com esperas de 1 s e 2 s e limite pelo timeout configurado. Nao repete 400/401/403/404/429, nao reexecuta ferramentas e nao muda modelo automaticamente. HUD indica tentativa e a resposta de erro explica indisponibilidade do Gemini. Requisicoes Gemini 3+ deixam de enviar temperatura personalizada conforme documentacao atual.

Alterados tambem core/orchestrator.py (mensagem de indisponibilidade). Validacao final automatizada: 74 testes passaram, incluindo 503 que recupera, 503 persistente limitado e chamada de ferramenta entregue apenas uma vez. HUD passou novamente sem erros JS. Validacao real dessa ultima alteracao aguarda reinicializacao do processo existente.

Orientacao de retry e compatibilidade: https://ai.google.dev/gemini-api/docs/troubleshooting

Referencias: https://ai.google.dev/api/models e https://ai.google.dev/api/generate-content


## Validacao real apos reinicializacao

Gemini 3.8 Flash respondeu com HTTP 200, status ok, sem erro, na primeira tentativa de geracao. A verificacao completa (metadados + frase publica minima) levou 50,08 s. Nao foram enviadas memoria, transcricoes ou ferramentas. Recuperacao real da geracao confirmada; latencia elevada permanece. Conversa por microfone, TTS e execucao de ferramentas nao foram exercitados nesta verificacao.
