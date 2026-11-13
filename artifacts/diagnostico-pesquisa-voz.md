# Pesquisa e cadastro de voz

Auditoria: duas chamadas reais a web.search terminaram no_relevant_results. A memoria local no intervalo correspondente registrou transformas em vez de Transformers; a continuacao universo padrao tipo existem varios primes perdeu a franquia. O algoritmo exigia tambem pra/sao/tipo/existem nos trechos. Consultas exatas e corpos dos resultados nao estavam no log; a reconstrucao veio do codigo e das transcricoes pertinentes.

core/research.py: reparo restrito transformas/transformos quando junto de Prime; remove palavras de apoio da relevancia; preserva contexto em continuacoes com entidades em comum; reconhece plural Primes; utiliza variante inglesa; recusa paginas genericas com apenas Optimus Prime em perguntas sobre o grupo. Tentativas continuam limitadas e nao ha fontes inventadas.

Teste real: DDG falhou; Bing RSS retornou repetidamente paginas genericas da franquia para consultas publicas diferentes. Com filtro corrigido, a pesquisa terminou honestamente sem fontes relevantes. Nao foi validada resposta completa correta sobre os Primes com esses provedores. O problema de disponibilidade/qualidade do provedor permanece.

Cadastro: data/voiceprint.json ausente. scripts/enroll_voice.py preparado com frases em portugues, nome do usuario, microfone explicito da configuracao, validacao basica do sinal, confirmacao e backup antes de substituir cadastro. Nao foi executado cadastro nem capturado audio. README_VIV.md contem comando e passos. Configuracao biometrica e limiares preservados.

Testes automatizados: regressao das frases observadas, contexto, tema novo, resultados irrelevantes e verificacao de dispositivo/sinal no cadastrador, sem microfone ou acoes reais. Testes publicos de busca realizados sem Gemini ou credenciais.
