/* Pop-ups da HUD.
   - Painel (esquerda): informação pedida — clima, pesquisa, tabelas, listas, visão. Um por vez, grande.
   - Avisos (direita): ações executadas e dados curtos. Somem sozinhos.
   - Confirmação (centro): ações perigosas.
   Todo texto vindo de eventos entra por textContent; nada é interpretado como HTML. */
(function () {
  'use strict';
  const layer = document.getElementById('cards');
  const links = document.getElementById('links');
  const confirmSlot = document.getElementById('confirm-slot');
  const PANEL_KINDS = { search: 1, vision: 1, content: 1, weather: 1 };
  const PANEL_LIFE = 75000, TOAST_LIFE = 8000, TOASTS = 4;
  const ICONS = { action: '›', search: '?', vision: '◉', data: 'i', content: '≡', weather: '☼' };
  const toasts = [];        // {el, slot, timer}
  let panel = null;         // {el, timer}
  let confirmTimer = null;

  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const narrow = () => window.matchMedia('(max-width: 760px)').matches;
  const safeUrl = url => /^https?:\/\//i.test(String(url || ''));

  // ---- posição e linhas conectoras -----------------------------------------
  function placeToast(card) {
    if (narrow()) { card.el.style.cssText = ''; return; }
    const top = 84, bottom = window.innerHeight - 210, slotH = Math.max(96, (bottom - top) / TOASTS);
    card.el.style.top = (top + card.slot * slotH) + 'px';
    card.el.style.maxHeight = (slotH - 12) + 'px';
  }

  function drawLinks() {
    while (links.firstChild) links.firstChild.remove();
    if (narrow() || !window.VivCore) return;
    const c = window.VivCore.center(), ns = 'http://www.w3.org/2000/svg';
    const items = toasts.map(t => [t.el, false]);
    if (panel) items.push([panel.el, true]);
    for (const [node, left] of items) {
      const box = node.getBoundingClientRect();
      if (!box.width) continue;
      const x1 = left ? box.right : box.left, y1 = box.top + Math.min(box.height / 2, 44);
      const angle = Math.atan2(y1 - c.y, x1 - c.x);
      const line = document.createElementNS(ns, 'line');
      line.setAttribute('x1', x1); line.setAttribute('y1', y1);
      line.setAttribute('x2', c.x + Math.cos(angle) * c.r); line.setAttribute('y2', c.y + Math.sin(angle) * c.r);
      const dot = document.createElementNS(ns, 'circle');
      dot.setAttribute('cx', x1); dot.setAttribute('cy', y1); dot.setAttribute('r', 2.5);
      links.append(line, dot);
    }
  }

  function vanish(node) {
    node.classList.remove('in'); node.classList.add('out');
    setTimeout(() => { node.remove(); drawLinks(); }, 380);
    drawLinks();
  }

  function removeToast(card) {
    const index = toasts.indexOf(card);
    if (index < 0) return;
    toasts.splice(index, 1);
    clearTimeout(card.timer);
    vanish(card.el);
  }

  function closePanel() {
    if (!panel) return;
    clearTimeout(panel.timer);
    vanish(panel.el);
    panel = null;
  }

  // ---- conteúdo -----------------------------------------------------------
  function content(body, format) {
    const lines = String(body || '').split('\n').map(s => s.trim()).filter(Boolean);
    if (format === 'lista') {
      const ul = el('ul');
      lines.forEach(item => ul.append(el('li', null, item.replace(/^[-*•]\s*/, ''))));
      return ul;
    }
    if (format === 'tabela') {
      const table = el('table');
      lines.filter(row => !/^[\s|:-]+$/.test(row)).forEach((row, i) => {
        const tr = el('tr');
        row.replace(/^\||\|$/g, '').split('|').forEach(cell => tr.append(el(i ? 'td' : 'th', null, cell.trim())));
        table.append(tr);
      });
      return table;
    }
    return el('p', 'card-body', body);
  }

  function results(list) {
    const box = el('div', 'results');
    list.slice(0, 5).forEach(item => {
      if (!safeUrl(item.url)) return;
      const row = el('div', 'result');
      const a = el('a', 'result-title', item.title || item.url);
      a.href = item.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
      let host = '';
      try { host = new URL(item.url).hostname.replace(/^www\./, ''); } catch (error) { /* url inválida */ }
      row.append(a, el('span', 'result-host', host));
      if (item.body) row.append(el('p', 'result-body', item.body));
      box.append(row);
    });
    return box;
  }

  function weather(w) {
    const box = el('div', 'weather');
    const now = el('div', 'weather-now');
    now.append(el('span', 'weather-temp', `${w.temp}°`));
    const side = el('div', 'weather-side');
    side.append(el('strong', null, w.desc || ''), el('span', null, `Sensação de ${w.feels}°`), el('span', null, `Mín ${w.min}° · Máx ${w.max}°`));
    now.append(side);
    const stats = el('div', 'weather-stats');
    [['Chuva', `${w.rain}%`], ['Umidade', `${w.humidity}%`], ['Vento', `${w.wind} km/h`]].forEach(([label, value]) => {
      const cell = el('div', 'weather-stat'); cell.append(el('b', null, value), el('span', null, label)); stats.append(cell);
    });
    const days = el('div', 'weather-days');
    (Array.isArray(w.days) ? w.days : []).slice(0, 4).forEach(d => {
      const cell = el('div', 'weather-day');
      cell.append(el('span', 'weather-day-label', d.label), el('b', null, `${d.max}°`), el('span', null, `${d.min}°`), el('span', 'weather-day-rain', `${d.rain}%`));
      cell.title = d.desc || '';
      days.append(cell);
    });
    box.append(now, stats, days);
    return box;
  }

  function build(event, kind) {
    const node = el('article', 'card');
    node.dataset.kind = kind;
    node.dataset.ok = event.ok === false ? 'false' : 'true';
    const head = el('div', 'card-head');
    head.append(el('span', 'card-icon', event.ok === false ? '!' : ICONS[kind]), el('span', 'card-title', event.text || ''));
    node.append(head);
    if (kind === 'weather' && event.weather && typeof event.weather === 'object') node.append(weather(event.weather));
    if (event.body) node.append(kind === 'content' ? content(event.body, event.format) : el('p', 'card-body', event.body));
    if (Array.isArray(event.results) && event.results.length) node.append(results(event.results));
    if (Array.isArray(event.sources) && event.sources.length) {
      const list = el('div', 'card-sources');
      event.sources.slice(0, 4).forEach(source => {
        if (!safeUrl(source.url)) return;
        const a = el('a', null, source.title || source.url);
        a.href = source.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
        list.append(a);
      });
      node.append(list);
    }
    if (kind === 'vision' && event.image === '/api/screen') {
      const img = el('img', 'card-shot'); img.alt = 'Captura da tela analisada'; img.src = '/api/screen?t=' + Date.now();
      node.append(img);
    }
    return node;
  }

  // ---- exibição -----------------------------------------------------------
  function show(event) {
    const kind = ICONS[event.kind] ? event.kind : 'action';
    const node = build(event, kind);
    if (PANEL_KINDS[kind]) {
      closePanel();
      node.classList.add('panel');
      const close = el('button', 'panel-close', '×');
      close.type = 'button'; close.setAttribute('aria-label', 'Fechar painel');
      close.addEventListener('click', closePanel);
      node.querySelector('.card-head').append(close);
      panel = { el: node, timer: setTimeout(closePanel, PANEL_LIFE) };
      layer.prepend(node);
    } else {
      node.classList.add('toast');
      const limit = narrow() ? 3 : TOASTS;
      while (toasts.length >= limit) removeToast(toasts[0]);
      const used = new Set(toasts.map(t => t.slot));
      let slot = 0;
      while (used.has(slot)) slot++;
      const card = { el: node, slot, timer: null };
      toasts.push(card);
      placeToast(card);
      layer.append(node);
      card.timer = setTimeout(() => removeToast(card), TOAST_LIFE);
    }
    node.querySelectorAll('.result, li, tr, .weather-stat, .weather-day').forEach((item, i) => item.style.setProperty('--i', Math.min(i, 24)));
    requestAnimationFrame(() => { node.classList.add('in'); setTimeout(drawLinks, 480); });
  }

  function confirmDone() {
    clearInterval(confirmTimer); confirmTimer = null;
    while (confirmSlot.firstChild) confirmSlot.firstChild.remove();
  }

  function confirm(event) {
    confirmDone();
    const total = Math.max(1, +event.seconds || 30), started = Date.now();
    const box = el('div', 'confirm');
    box.setAttribute('role', 'alertdialog'); box.setAttribute('aria-label', 'Confirmar ação');
    const hint = el('p', 'confirm-hint', event.voice === false ? 'Clique em Sim para confirmar, ou em Não para cancelar.'
      : 'Diga “sim” ou “não”, ou escolha abaixo.');
    hint.id = 'confirm-hint';
    const bar = el('div', 'confirm-bar'), fill = el('i'); bar.append(fill);
    const actions = el('div', 'confirm-actions');
    const no = el('button', 'no', 'Não'), yes = el('button', 'yes', 'Sim');
    no.type = yes.type = 'button';
    const send = decision => { yes.disabled = no.disabled = true; fetch('/api/confirm/' + decision, { method: 'POST' }).catch(() => { yes.disabled = no.disabled = false; }); };
    yes.addEventListener('click', () => send('sim'));
    no.addEventListener('click', () => send('nao'));
    actions.append(no, yes);
    box.append(el('p', 'confirm-kicker', 'Confirmar ação'), el('p', 'confirm-text', event.text || event.name || ''), hint, bar, actions);
    confirmSlot.append(box);
    confirmTimer = setInterval(() => {
      const left = Math.max(0, 1 - (Date.now() - started) / (total * 1000));
      fill.style.transform = `scaleX(${left})`;
      if (!left) confirmDone();
    }, 100);
  }

  function hint(text) {
    const node = document.getElementById('confirm-hint');
    if (node) node.textContent = text;
  }

  const relayout = () => {
    while (toasts.length > (narrow() ? 3 : TOASTS)) removeToast(toasts[0]);
    toasts.forEach(placeToast); drawLinks();
  };
  window.addEventListener('resize', relayout);
  window.addEventListener('viv-core-moved', drawLinks);
  window.VivCards = { show, confirm, confirmDone, hint, closePanel };
})();
