/* Liga a HUD ao servidor: WebSocket de eventos, estado, legenda e botão de ativação. */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const LABELS = { sleeping: 'Dormindo', listening: 'Ouvindo', thinking: 'Pensando', speaking: 'Falando', executing: 'Executando', error: 'Erro' };
  let state = 'sleeping', socket = null, retry = null, captionTimer = null, progressTimer = null;

  // Barra de progresso: só aparece se a tarefa passar de um instante, para não piscar a cada ação.
  function progress(event) {
    const box = $('progress'), fill = $('progress-fill');
    if (event.done) {
      clearTimeout(progressTimer); progressTimer = null;
      box.hidden = true;
      return;
    }
    $('progress-label').textContent = event.text || 'Trabalhando';
    const known = typeof event.value === 'number';
    box.classList.toggle('unknown', !known);
    fill.style.transform = known ? `scaleX(${Math.max(.03, Math.min(1, event.value))})` : '';
    if (box.hidden && !progressTimer) progressTimer = setTimeout(() => { progressTimer = null; box.hidden = false; }, 900);
  }

  function mood(data) {
    const chip = $('mood'), root = document.documentElement, colors = data && data.palette;
    chip.hidden = !(data && data.enabled);
    if (!data) return;
    chip.textContent = data.label || data.text || '';
    if (!Array.isArray(colors) || colors.length < 3 || !colors.every(c => /^#[0-9a-f]{6}$/i.test(c))) return;
    root.style.setProperty('--viv-rose', colors[0]);
    root.style.setProperty('--viv-violet', colors[1]);
    root.style.setProperty('--viv-cyan', colors[2]);
    root.style.setProperty('--viv-line', colors[1] + '61');
    window.VivCore.setPalette(colors[0], colors[1], colors[2]);
  }

  function speaker(data) {
    const chip = $('who');
    chip.hidden = !data;
    if (!data) return;
    chip.textContent = data.known ? (data.name || data.text || 'voz reconhecida') : 'voz não reconhecida';
    chip.dataset.known = data.known ? 'true' : 'false';
  }

  function setState(next, reconnecting) {
    if (!LABELS[next]) return;
    // ela parou de falar e voltou a ouvir: hora do painel com todas as conversas
    if (state === 'speaking' && next === 'listening') window.VivWhatsApp.turnEnd();
    if (next === 'sleeping') window.VivWhatsApp.close();
    state = next;
    document.body.dataset.state = next;
    $('state-label').textContent = LABELS[next];
    $('conn').hidden = !reconnecting;
    $('wake').textContent = next === 'sleeping' || next === 'error' ? 'Ativar Viv' : 'Dormir';
    window.VivCore.setState(next);
    if (next === 'sleeping') {
      speaker(null);
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
      window.VivWhatsApp.heard(event.text);
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
      case 'progress': progress(event); break;
      case 'whatsapp': window.VivWhatsApp.handle(event); break;
      case 'mood': mood({ label: event.text, palette: event.palette, enabled: event.enabled }); break;
      case 'speaker': speaker({ name: event.text, known: event.known }); break;
    }
  }

  async function status() {
    try {
      const data = await (await fetch('/api/status')).json();
      setState(data.state);
      $('mic').textContent = data.mic || '';
      mood(data.mood); speaker(data.speaker);
      // o tempo que resta vem do servidor: reabrir a tela não reinicia a contagem nem ressuscita um pedido vencido
      if (data.pending && data.pending.seconds > 0) window.VivCards.confirm({ text: data.pending.text, voice: data.pending.voice, seconds: data.pending.seconds });
      else window.VivCards.confirmDone();
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
