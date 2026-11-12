/* Pop-ups da HUD: cartões ao redor do núcleo e o cartão de confirmação.
   Todo texto vindo de eventos entra por textContent; nada é interpretado como HTML. */
(function () {
  'use strict';
  const layer = document.getElementById('cards');
  const links = document.getElementById('links');
  const confirmSlot = document.getElementById('confirm-slot');
  const MAX = 5;
  const LIFE = { action: 8000, data: 9000, search: 20000, vision: 20000, content: 25000 };
  const ICONS = { action: '›', search: '?', vision: '◉', data: 'i', content: '≡' };
  // ordem de ocupação: direita e esquerda alternadas, de cima para baixo
  const SLOTS = [['right', 0], ['left', 0], ['right', 1], ['left', 1], ['right', 2]];
  const active = [];   // {el, slot, timer}
  let confirmTimer = null;

  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const narrow = () => window.matchMedia('(max-width: 760px)').matches;

  function place(card) {
    if (narrow()) { card.el.style.cssText = ''; return; }
    const [side, row] = SLOTS[card.slot];
    const top = 84, bottom = window.innerHeight - 210, slotH = Math.max(120, (bottom - top) / 3);
    card.el.style.top = (top + row * slotH) + 'px';
    card.el.style.maxHeight = (slotH - 14) + 'px';
    card.el.style[side] = '3.2vw';
    card.el.style[side === 'left' ? 'right' : 'left'] = 'auto';
    card.el.style.setProperty('--from', side === 'left' ? '-28px' : '28px');
  }

  function drawLinks() {
    while (links.firstChild) links.firstChild.remove();
    if (narrow() || !window.VivCore) return;
    const c = window.VivCore.center();
    for (const card of active) {
      const box = card.el.getBoundingClientRect();
      if (!box.width) continue;
      const left = SLOTS[card.slot][0] === 'left';
      const x1 = left ? box.right : box.left, y1 = box.top + Math.min(box.height / 2, 40);
      const angle = Math.atan2(y1 - c.y, x1 - c.x);
      const x2 = c.x + Math.cos(angle) * c.r, y2 = c.y + Math.sin(angle) * c.r;
      const ns = 'http://www.w3.org/2000/svg';
      const line = document.createElementNS(ns, 'line');
      line.setAttribute('x1', x1); line.setAttribute('y1', y1); line.setAttribute('x2', x2); line.setAttribute('y2', y2);
      const dot = document.createElementNS(ns, 'circle');
      dot.setAttribute('cx', x1); dot.setAttribute('cy', y1); dot.setAttribute('r', 2.5);
      links.append(line, dot);
    }
  }

  function remove(card) {
    const index = active.indexOf(card);
    if (index < 0) return;
    active.splice(index, 1);
    clearTimeout(card.timer);
    card.el.classList.remove('in'); card.el.classList.add('out');
    setTimeout(() => { card.el.remove(); drawLinks(); }, 400);
    drawLinks();
  }

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

  function show(event) {
    const kind = LIFE[event.kind] ? event.kind : 'action';
    const node = el('article', 'card');
    node.dataset.kind = kind;
    node.dataset.ok = event.ok === false ? 'false' : 'true';
    const head = el('div', 'card-head');
    head.append(el('span', 'card-icon', event.ok === false ? '!' : ICONS[kind]), el('span', 'card-title', event.text || ''));
    node.append(head);
    if (event.body) node.append(kind === 'content' ? content(event.body, event.format) : el('p', 'card-body', event.body));
    if (Array.isArray(event.sources) && event.sources.length) {
      const list = el('div', 'card-sources');
      event.sources.slice(0, 4).forEach(source => {
        if (!/^https?:\/\//i.test(String(source.url || ''))) return;
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
    const limit = narrow() ? 3 : MAX;
    while (active.length >= limit) remove(active[0]);
    const used = new Set(active.map(c => c.slot));
    const slot = SLOTS.findIndex((_, i) => !used.has(i));
    const card = { el: node, slot: slot < 0 ? 0 : slot, timer: null };
    active.push(card);
    place(card);
    layer.append(node);
    requestAnimationFrame(() => { node.classList.add('in'); setTimeout(drawLinks, 480); });
    card.timer = setTimeout(() => remove(card), LIFE[kind]);
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
    const hint = el('p', 'confirm-hint', 'Diga “sim” ou “não”, ou escolha abaixo.');
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
    while (active.length > (narrow() ? 3 : MAX)) remove(active[0]);
    active.forEach(place); drawLinks();
  };
  window.addEventListener('resize', relayout);
  window.addEventListener('viv-core-moved', drawLinks);
  window.VivCards = { show, confirm, confirmDone, hint };
})();
