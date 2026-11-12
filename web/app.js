/* Liga a HUD ao servidor: WebSocket de eventos, estado, legenda e botão de ativação. */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const LABELS = { sleeping: 'Dormindo', listening: 'Ouvindo', thinking: 'Pensando', speaking: 'Falando', executing: 'Executando', error: 'Erro' };
  let state = 'sleeping', socket = null, retry = null, captionTimer = null;

  function setState(next, reconnecting) {
    if (!LABELS[next]) return;
    state = next;
    document.body.dataset.state = next;
    $('state-label').textContent = LABELS[next];
    $('conn').hidden = !reconnecting;
    $('wake').textContent = next === 'sleeping' || next === 'error' ? 'Ativar Viv' : 'Dormir';
    window.VivCore.setState(next);
    if (next === 'sleeping') {
      clearTimeout(captionTimer);
      captionTimer = setTimeout(() => { $('caption-user').textContent = ''; $('caption-viv').textContent = ''; }, 6000);
    }
  }

  function transcript(event) {
    clearTimeout(captionTimer);
    if (event.role === 'user') {
      $('caption-user').textContent = event.text || '';
      if (!event.final) $('caption-viv').textContent = '';
    } else {
      $('caption-viv').textContent = event.text || '';
    }
  }

  function handle(event) {
    if (!event || typeof event !== 'object') return;
    switch (event.channel) {
      case 'state': setState(event.state, event.reconnecting); break;
      case 'level': window.VivCore.setLevel(event.source, event.value); break;
      case 'transcript': transcript(event); break;
      case 'card': window.VivCards.show(event); break;
      case 'confirm': window.VivCards.confirm(event); break;
      case 'confirm_hint': window.VivCards.hint(event.text); break;
      case 'confirm_done': window.VivCards.confirmDone(); break;
    }
  }

  async function status() {
    try {
      const data = await (await fetch('/api/status')).json();
      setState(data.state);
      $('mic').textContent = data.mic || '';
      if (data.pending) window.VivCards.confirm({ text: data.pending.text, voice: data.pending.voice, seconds: 30 });
    } catch (error) { /* o WebSocket cuida de reconectar */ }
  }

  function connect() {
    clearTimeout(retry);
    socket = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
    socket.addEventListener('open', () => { $('conn').hidden = true; status(); });
    socket.addEventListener('message', message => { try { handle(JSON.parse(message.data)); } catch (error) { /* evento inválido */ } });
    socket.addEventListener('close', () => {
      $('conn').hidden = false; $('conn').textContent = 'sem contato com a Viv…';
      retry = setTimeout(connect, 1500);
    });
  }

  $('wake').addEventListener('click', () => {
    fetch(state === 'sleeping' || state === 'error' ? '/api/wake' : '/api/sleep', { method: 'POST' }).catch(() => {});
  });
  const tick = () => { $('clock').textContent = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }); };
  tick(); setInterval(tick, 10000);

  window.VivHUD = { handle };
  if (!new URLSearchParams(location.search).has('offline')) connect();
})();
