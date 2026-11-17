/* Miniatura: só o avatar, numa janelinha no canto da tela enquanto a Viv está minimizada.
   Recebe os mesmos eventos da HUD e os repassa ao avatar. Um “!” avisa que há uma confirmação ou pergunta
   esperando na janela principal; clicar na miniatura abre a janela principal. */
(function () {
  'use strict';
  const avatar = window.VivAvatar, box = document.getElementById('avatar'), alert = document.getElementById('alert');
  if (!avatar) return;
  let retry = null, tasks = false;

  function mood(data) {
    avatar.setMood(data);
    // o LED é sempre azul: a borda também
  }

  function handle(event) {
    switch (event.channel) {
      case 'state': avatar.setState(event.state); avatar.setHibernating(!!event.hibernating); break;
      case 'level': avatar.setLevel(event.source, event.value); break;
      case 'music': avatar.setMusic(event); break;
      case 'hud': if (typeof event.motion === 'boolean') document.documentElement.dataset.motion = event.motion ? 'full' : ''; break;
      case 'mood': mood({ name: event.name, label: event.text, palette: event.palette, enabled: event.enabled }); break;
      case 'card': if (!event.wa) avatar.react(event.ok === false ? 'oops' : event.kind === 'action' ? 'done' : ''); break;
      case 'confirm': avatar.setAsking(true); alert.hidden = false; break;
      case 'confirm_done': avatar.setAsking(false); alert.hidden = true; break;
      case 'ask': avatar.react('curious'); alert.hidden = false; break;
      case 'ask_done': alert.hidden = true; break;
      case 'tasks': {
        const running = Array.isArray(event.items) && event.items.length > 0;
        avatar.setBusy(running);
        if (tasks && !running) avatar.react('cheer');
        tasks = running;
        break;
      }
    }
  }

  async function status() {
    try {
      const data = await (await fetch('/api/status')).json();
      avatar.setState(data.state); avatar.setHibernating(!!data.hibernating);
      mood(data.mood);
      avatar.setAsking(!!data.pending); alert.hidden = !data.pending;
    } catch (error) { /* o WebSocket reconecta */ }
  }

  function connect() {
    clearTimeout(retry);
    const socket = new WebSocket('ws://' + location.host + '/ws');
    socket.addEventListener('open', status);
    socket.addEventListener('message', message => { try { handle(JSON.parse(message.data)); } catch (error) { /* evento inválido */ } });
    socket.addEventListener('close', () => { retry = setTimeout(connect, 1500); });
  }

  // arrastar move a janelinha; só um clique parado abre a Viv
  let downAt = null;
  box.addEventListener('pointerdown', event => { downAt = [event.screenX, event.screenY]; });
  box.addEventListener('pointerup', event => {
    if (downAt && Math.hypot(event.screenX - downAt[0], event.screenY - downAt[1]) < 5) fetch('/api/mini/abrir', { method: 'POST' }).catch(() => {});
    downAt = null;
  });

  avatar.show(true);
  window.VivMini = { handle };
  if (!new URLSearchParams(location.search).has('offline')) connect();
})();
