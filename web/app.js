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

  // Tarefas em segundo plano: uma linha por tarefa, atualizada no lugar para a barra não recomeçar.
  function tasks(event) {
    const box = $('tasks'), items = Array.isArray(event.items) ? event.items : [];
    const keep = new Set(items.map(item => String(item.id)));
    [...box.children].forEach(row => { if (!keep.has(row.dataset.id)) row.remove(); });
    items.forEach(item => {
      let row = [...box.children].find(r => r.dataset.id === String(item.id));
      if (!row) {
        row = document.createElement('div'); row.className = 'task'; row.dataset.id = String(item.id);
        const label = document.createElement('span'), track = document.createElement('div');
        track.className = 'progress-track'; track.appendChild(document.createElement('i'));
        row.append(label, track); box.appendChild(row);
      }
      const known = typeof item.value === 'number';
      row.firstChild.textContent = item.step ? `${item.title} · ${item.step}` : (item.title || 'Trabalhando');
      row.classList.toggle('unknown', !known);
      row.querySelector('i').style.transform = known ? `scaleX(${Math.max(.03, Math.min(1, item.value))})` : '';
    });
    box.hidden = !items.length;
  }

  function mood(data) {
    const chip = $('mood'), root = document.documentElement, colors = data && data.palette;
    chip.hidden = !(data && data.enabled);
    if (!data) return;
    if (window.VivAvatar) window.VivAvatar.setMood(data);
    chip.textContent = data.label || data.text || '';
    if (!Array.isArray(colors) || colors.length < 3 || !colors.every(c => /^#[0-9a-f]{6}$/i.test(c))) return;
    root.style.setProperty('--viv-rose', colors[0]);
    root.style.setProperty('--viv-violet', colors[1]);
    root.style.setProperty('--viv-cyan', colors[2]);
    window.VivCore.setPalette(colors[0], colors[1], colors[2]);
  }

  function speaker(data) {
    const chip = $('who');
    chip.hidden = !data;
    if (!data) return;
    chip.textContent = data.known ? (data.name || data.text || 'voz reconhecida') : 'voz não reconhecida';
    chip.dataset.known = data.known ? 'true' : 'false';
  }

  // Quem está na conversa: os nomes conhecidos vão para o topo; vozes não cadastradas viram só um “+1”.
  let talking = '';
  function present(people) {
    const chip = $('present'), names = (Array.isArray(people) ? people : []).map(String);
    const known = names.filter(name => !/^voz desconhecida/.test(name)), extra = names.length - known.length;
    chip.hidden = names.length < 2;
    $('who').classList.toggle('merged', !chip.hidden);
    chip.textContent = '';
    known.forEach(name => { const tag = document.createElement('b'); tag.textContent = name; if (name === talking) tag.className = 'now'; chip.append(tag); });
    if (extra > 0) { const more = document.createElement('i'); more.textContent = '+' + extra; more.title = 'voz não cadastrada'; chip.append(more); }
  }

  let hibernating = false;
  function setState(next, reconnecting, sleepsDeep) {
    if (!LABELS[next]) return;
    hibernating = next === 'sleeping' && !!sleepsDeep;
    document.body.dataset.hibernating = hibernating ? 'true' : 'false';
    if (window.VivAvatar) window.VivAvatar.setHibernating(hibernating);
    // ela parou de falar e voltou a ouvir: hora do painel com todas as conversas
    if (state === 'speaking' && next === 'listening') window.VivWhatsApp.turnEnd();
    if (next === 'sleeping') window.VivWhatsApp.close();
    state = next;
    document.body.dataset.state = next;
    $('state-label').textContent = hibernating ? 'Hibernando' : LABELS[next];
    $('hint').textContent = hibernating ? 'Hibernando: não ouço nem o meu nome. Clique em Ativar ou use Ctrl+Alt+V.'
      : 'Diga “Ei, Viv”, bata duas palmas ou aperte Ctrl+Alt+V.';
    $('hibernate').hidden = hibernating;
    $('conn').hidden = !reconnecting;
    $('wake').textContent = next === 'sleeping' || next === 'error' ? 'Ativar Viv' : 'Dormir';
    window.VivCore.setState(next);
    if (window.VivAvatar) window.VivAvatar.setState(next);
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
    if (window.VivChat) window.VivChat.transcript(event);
  }

  function handle(event) {
    if (!event || typeof event !== 'object') return;
    switch (event.channel) {
      case 'state': setState(event.state, event.reconnecting, event.hibernating); break;
      case 'level': window.VivCore.setLevel(event.source, event.value); if (window.VivAvatar) window.VivAvatar.setLevel(event.source, event.value); break;
      case 'transcript': transcript(event); break;
      case 'card':
        window.VivCards.show(event);
        if (window.VivAvatar && !event.wa) window.VivAvatar.react(event.ok === false ? 'oops' : event.kind === 'action' ? 'done' : '');
        break;
      case 'confirm': window.VivCards.confirm(event); if (window.VivAvatar) window.VivAvatar.setAsking(true); break;
      case 'confirm_hint': window.VivCards.hint(event.text); break;
      case 'confirm_done': window.VivCards.confirmDone(); if (window.VivAvatar) window.VivAvatar.setAsking(false); break;
      case 'ask': window.VivCards.ask(event); if (window.VivAvatar) window.VivAvatar.react('curious'); break;
      case 'ask_done': window.VivCards.askDone(); break;
      case 'progress': progress(event); break;
      case 'tasks': {
        const running = Array.isArray(event.items) && event.items.length > 0, was = !$('tasks').hidden;
        tasks(event);
        if (window.VivAvatar) { window.VivAvatar.setBusy(running); if (was && !running) window.VivAvatar.react('cheer'); }
        break;
      }
      case 'whatsapp': window.VivWhatsApp.handle(event); break;
      case 'mood': mood({ name: event.name, label: event.text, palette: event.palette, enabled: event.enabled }); break;
      case 'hud':
        if (window.VivAvatar && typeof event.avatar === 'boolean') window.VivAvatar.show(event.avatar);
        if (window.VivAvatar && event.look) window.VivAvatar.setLook(event.look);
        if (typeof event.motion === 'boolean') document.documentElement.dataset.motion = event.motion ? 'full' : '';
        break;
      case 'speaker':
        talking = event.known ? event.text || '' : '';
        speaker({ name: event.text, known: event.known });
        [...$('present').querySelectorAll('b')].forEach(tag => tag.classList.toggle('now', tag.textContent === talking));
        break;
      case 'presence': present(event.people); break;
      case 'chat': if (window.VivChat) window.VivChat.handle(event); break;
      case 'music': if (window.VivAvatar) window.VivAvatar.setMusic(event); break;
    }
  }

  async function status() {
    try {
      const data = await (await fetch('/api/status')).json();
      setState(data.state, false, data.hibernating);
      present(data.present);
      if (window.VivChat) window.VivChat.handle({ text_only: !!data.text_only });
      $('mic').textContent = data.mic || '';
      mood(data.mood); speaker(data.speaker);
      if (window.VivAvatar) { window.VivAvatar.show(data.avatar !== false); if (data.avatar_look) window.VivAvatar.setLook(data.avatar_look); }
      // o tempo que resta vem do servidor: reabrir a tela não reinicia a contagem nem ressuscita um pedido vencido
      if (data.pending && data.pending.seconds > 0) window.VivCards.confirm({ text: data.pending.text, voice: data.pending.voice, seconds: data.pending.seconds, immediate: true });
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
  $('hibernate').addEventListener('click', () => { fetch('/api/hibernate', { method: 'POST' }).catch(() => {}); });
  const tick = () => { $('clock').textContent = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }); };
  tick(); setInterval(tick, 10000);

  window.VivHUD = { handle };
  if (!new URLSearchParams(location.search).has('offline')) connect();
})();
