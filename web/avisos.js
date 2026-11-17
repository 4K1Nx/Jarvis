/* Avisos com a Viv minimizada: os mesmos cartões do canto superior direito da HUD, numa janelinha própria
   (viv/mini.py) que cresce e encolhe para caber neles e some quando não há nenhum. Clicar num aviso abre a Viv. */
(function () {
  'use strict';
  const stack = document.getElementById('stack');
  const LIFE = 8000, MAX = 3;
  const PANELS = { search: 1, vision: 1, content: 1, weather: 1, chart: 1, briefing: 1 };
  let retry = null, fitted = -1;

  // tamanho da janela = tamanho dos avisos; sem avisos, ela some (viv/mini.py, Notices.fit)
  function fit() {
    requestAnimationFrame(() => {
      const height = stack.children.length ? Math.ceil(stack.getBoundingClientRect().height) : 0;
      if ((height === fitted && height > 0) || !window.pywebview || !window.pywebview.api) return;
      fitted = height;
      window.pywebview.api.fit(height, window.devicePixelRatio || 1).catch(() => {});
    });
  }

  function remove(node) {
    if (!node.isConnected || node.classList.contains('out')) return;
    node.classList.remove('in'); node.classList.add('out');
    setTimeout(() => { node.remove(); fit(); }, 360);
  }

  function show(event) {
    if (PANELS[event.kind] || !window.VivToast) return;
    const node = window.VivToast.build(event);
    while (stack.children.length >= MAX) stack.lastElementChild.remove();
    stack.prepend(node);
    const track = document.createElement('div'), fill = document.createElement('i');
    track.className = 'card-life'; track.append(fill);
    fill.style.animationDuration = LIFE + 'ms';
    fill.addEventListener('animationend', () => remove(node));
    setTimeout(() => remove(node), LIFE + 1500);     // com a janela escondida a barrinha não anda: o relógio garante a saída
    node.append(track);
    node.addEventListener('click', () => { fetch('/api/mini/abrir', { method: 'POST' }).catch(() => {}); remove(node); });
    node.querySelectorAll('img').forEach(img => img.addEventListener('load', fit));
    requestAnimationFrame(() => node.classList.add('in'));
    fit();
  }

  function connect() {
    clearTimeout(retry);
    const socket = new WebSocket('ws://' + location.host + '/ws');
    socket.addEventListener('message', message => {
      try { const event = JSON.parse(message.data); if (event.channel === 'card') show(event); } catch (error) { /* evento inválido */ }
    });
    socket.addEventListener('close', () => { retry = setTimeout(connect, 1500); });
  }

  window.addEventListener('pywebviewready', fit);
  window.VivAvisos = { show };
  if (!new URLSearchParams(location.search).has('offline')) connect();
})();
