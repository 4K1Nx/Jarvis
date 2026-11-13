# Diagnostico de ativacao

- Diretorio confirmado: C:/Users/jvpmc/Viv; main.py, config.yaml e core presentes.
- Servidor ativo consultado por HTTP: captura USB OK, quadros recentes, zero erros no filtro; estado Gemini error/model_not_found. Nao foi consultado conteudo pessoal.
- Erros 503 reportados nao correspondem ao handler /api/wake atual. Recusa de conexao indica ausencia momentanea do servidor; causa desse encerramento nao confirmada. Log nativo recente nao apresenta nova falha fatal. Eventos Windows mostraram apenas falhas nativas anteriores.
- Pendencias continuam disponiveis na HUD e por pergunta; anuncio falado ao iniciar passou a exigir assistant.announce_gaps_on_start=true.
- Erros de conversa agora registram tipo/local seguro e explicacao falada, sem repetir ferramentas. Falha do TTS dessa explicacao fica contida.
- Botao Verificar conexao agora faz geracao publica minima sem memoria nem ferramentas; verificacao automatica de inicializacao continua apenas metadados. Nenhuma troca automatica de modelo ou credencial.
- /api/status identifica PID/revisao; botao de ativacao distingue erro HTTP de servidor sem resposta.
- Validacao: 55 testes automatizados passaram, usando mocks para Gemini/audio/acoes. Primeira tentativa de TestClient bloqueou em socketpair no sandbox; interrompida e repetida com permissao de sockets locais.
- Pendente: reiniciar processo para carregar alteracoes, verificar geracao real pelo botao, testar conversa/interrupcao com hardware. Nao foi comprovada recuperacao da geracao Gemini nem explicada definitivamente a queda anterior.
