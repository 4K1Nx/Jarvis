/* Biblioteca dos apps da Viv: liga um projeto feito por ela à própria Viv, ao vivo.

   <script src="/apps/viv-app.js"></script>

   Viv.acoes({ mover: 'dados {de, para}, casas como "e7"' })   o que a Viv pode mandar o app fazer
   Viv.ao('mover', dados => { ... })        obedece a um comando dela; lançar um erro diz a ela que não deu certo
   Viv.estado({ ... })                      o estado atual, sempre que mudar (ela consulta quando precisa)
   Viv.evento('O jogador moveu e2 para e4', { ... })   algo que pede reação dela agora (ela é avisada na hora)
   Viv.conectada                            true enquanto a ligação está aberta

   A ligação se refaz sozinha se cair. Mensagens enviadas antes de conectar esperam na fila. */
(function () {
  'use strict';
  const slug = decodeURIComponent(location.pathname.split('/')[2] || '');
  const handlers = {}, actions = {};
  let socket = null, queue = [], lastState = null;

  function send(message) {
    const text = JSON.stringify(message);
    if (socket && socket.readyState === WebSocket.OPEN) socket.send(text);
    else if (message.type !== 'estado') queue.push(text);      // do estado, só o último interessa
  }

  function connect() {
    socket = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/apps/' + encodeURIComponent(slug) + '/ws');
    socket.addEventListener('open', () => {
      Viv.conectada = true;
      socket.send(JSON.stringify({ type: 'acoes', acoes: actions }));
      if (lastState !== null) socket.send(JSON.stringify({ type: 'estado', dados: lastState }));
      queue.splice(0).forEach(text => socket.send(text));
      document.dispatchEvent(new CustomEvent('viv-conectada'));
    });
    socket.addEventListener('message', async event => {
      let message;
      try { message = JSON.parse(event.data); } catch (error) { return; }
      if (!message || message.type !== 'comando') return;
      const handler = handlers[message.acao] || handlers['*'];
      let ok = true, erro = '';
      try {
        if (!handler) throw new Error('ação desconhecida: ' + message.acao);
        await handler(message.dados || {}, message.acao);
      } catch (error) { ok = false; erro = String((error && error.message) || error); }
      send({ type: 'resposta', id: message.id, ok, erro });
    });
    socket.addEventListener('close', () => { Viv.conectada = false; setTimeout(connect, 1500); });
  }

  const Viv = {
    conectada: false,
    acoes(map) { Object.assign(actions, map || {}); send({ type: 'acoes', acoes: actions }); },
    ao(acao, fn) { handlers[acao] = fn; },
    estado(dados) { lastState = dados; send({ type: 'estado', dados }); },
    evento(texto, dados) { if (dados !== undefined) lastState = dados; send({ type: 'evento', texto: String(texto), dados }); },
  };
  window.Viv = Viv;
  if (slug) connect();
})();
