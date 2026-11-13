/* Pop-ups da HUD.
   - Painel (esquerda): informação pedida — clima, pesquisa, tabelas, listas, visão. Um por vez, grande.
   - Avisos (direita): ações executadas e dados curtos. Somem sozinhos.
   - Confirmação (centro): ações perigosas.
   Cada cartão tem uma barrinha que encolhe até a hora de sair; o tempo pausa com o mouse em cima.
   Todo texto vindo de eventos entra por textContent; nada é interpretado como HTML. A formatação
   (negrito, títulos, listas, tabelas, código) é montada nó a nó a partir de marcações simples. */
(function () {
  'use strict';
  const layer = document.getElementById('cards');
  const links = document.getElementById('links');
  const confirmSlot = document.getElementById('confirm-slot');
  const PANEL_KINDS = { search: 1, vision: 1, content: 1, weather: 1 };
  const PANEL_LIFE = 75000, TOAST_LIFE = 8000, TOASTS = 4;
  const KINDS = { action: 1, search: 1, vision: 1, data: 1, content: 1, weather: 1 };
  const toasts = [];        // {el}, na ordem em que chegaram
  let panel = null;         // {el}
  let confirmTimer = null;

  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const narrow = () => window.matchMedia('(max-width: 760px)').matches;
  const safeUrl = url => /^https?:\/\//i.test(String(url || ''));

  // ---- posição e linhas conectoras -----------------------------------------
  // Avisos empilhados de cima para baixo, um logo abaixo do outro, na ordem em que chegaram.
  function placeToasts() {
    const top = 72, gap = 10, room = window.innerHeight - 210 - top;
    let y = top;
    toasts.forEach(card => {
      if (narrow()) { card.el.style.cssText = ''; return; }
      card.el.style.maxHeight = Math.max(88, room / TOASTS - gap) + 'px';
      card.el.style.top = y + 'px';
      y += card.el.offsetHeight + gap;
    });
  }

  // linhas conectoras: de cada cartão até a borda do núcleo
  function drawLinks() {
    if (!links) return;
    while (links.firstChild) links.firstChild.remove();
    if (narrow() || !window.VivCore) return;
    const c = window.VivCore.center(), ns = 'http://www.w3.org/2000/svg';
    const items = toasts.map(t => [t.el, false]);
    if (panel) items.push([panel.el, true]);
    for (const [node, left] of items) {
      const box = node.getBoundingClientRect();
      if (!box.width) continue;
      const x1 = left ? box.right : box.left, y1 = box.top + Math.min(box.height / 2, 36);
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
    vanish(card.el);
    placeToasts();
  }

  function closePanel() {
    if (!panel) return;
    vanish(panel.el);
    panel = null;
    stack();
  }

  // O painel (rascunho, lista) e a conversa do WhatsApp ficam os dois à esquerda: em vez de um por
  // cima do outro, o painel fica em cima, mais baixo, e a conversa logo abaixo dele.
  function stack() {
    const wa = document.getElementById('wa');
    if (!wa) return;
    const both = !!panel && !narrow() && !!wa.querySelector('.wa-card:not(.out)');
    document.body.classList.toggle('stacked', both);
    if (!both) { wa.style.top = ''; return; }
    requestAnimationFrame(() => {
      if (!panel) return;
      wa.style.top = Math.round(panel.el.getBoundingClientRect().bottom + 12) + 'px';
      drawLinks();
    });
  }
  window.addEventListener('resize', stack);

  // ---- formatação ----------------------------------------------------------
  const INLINE = /\*\*([^*\n]+)\*\*|__([^_\n]+)__|\*([^*\s][^*\n]*)\*|`([^`\n]+)`|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<>"')\]]+)/g;

  /* Acrescenta `text` a `target` com **negrito**, *itálico*, `código` e links http(s). */
  function inline(target, text) {
    text = String(text == null ? '' : text);
    let last = 0;
    for (const m of text.matchAll(INLINE)) {
      if (m.index > last) target.append(text.slice(last, m.index));
      if (m[1] || m[2]) target.append(el('strong', null, m[1] || m[2]));
      else if (m[3]) target.append(el('em', null, m[3]));
      else if (m[4]) target.append(el('code', null, m[4]));
      else {
        const a = el('a', null, m[5] || m[7]);
        a.href = m[6] || m[7]; a.target = '_blank'; a.rel = 'noopener noreferrer';
        target.append(a);
      }
      last = m.index + m[0].length;
    }
    if (last < text.length) target.append(text.slice(last));
    return target;
  }

  const SEPARATOR = /^[\s|:-]+$/, ITEM = /^\s*(?:[-*•]|\d+[.)])\s+/;
  const cells = row => row.trim().replace(/^\||\|$/g, '').split('|').map(cell => cell.trim());

  function table(rows) {
    const node = el('table');
    rows.filter(row => !SEPARATOR.test(row)).forEach((row, i) => {
      const tr = el('tr');
      cells(row).forEach(cell => tr.append(inline(el(i ? 'td' : 'th'), cell)));
      node.append(tr);
    });
    return node;
  }

  function list(rows, ordered) {
    const node = el(ordered ? 'ol' : 'ul');
    rows.forEach(row => {
      const text = row.replace(ITEM, ''), todo = /^\[( |x|X)\]\s+/.exec(text);
      const li = inline(el('li'), todo ? text.slice(todo[0].length) : text);
      if (todo) { li.className = 'todo'; li.dataset.done = todo[1] === ' ' ? 'false' : 'true'; }
      node.append(li);
    });
    return node;
  }

  /* Texto com marcações simples vira títulos, listas, tabelas, citações e blocos de código. */
  function rich(body) {
    const box = el('div', 'md'), lines = String(body || '').replace(/\r/g, '').split('\n');
    let i = 0;
    const take = test => { const rows = []; while (i < lines.length && test(lines[i])) rows.push(lines[i++]); return rows; };
    while (i < lines.length) {
      const line = lines[i], heading = /^(#{1,4})\s+(.*)$/.exec(line.trim());
      if (!line.trim()) { i++; continue; }
      if (/^\s*```/.test(line)) {
        i++;
        const code = take(row => !/^\s*```/.test(row));
        i++;
        const pre = el('pre'); pre.append(el('code', null, code.join('\n'))); box.append(pre);
      } else if (heading) {
        box.append(inline(el('h4', 'md-h' + heading[1].length), heading[2])); i++;
      } else if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        box.append(el('hr')); i++;
      } else if (/^\s*>/.test(line)) {
        const quote = el('blockquote');
        take(row => /^\s*>/.test(row)).forEach((row, n) => { if (n) quote.append(el('br')); inline(quote, row.replace(/^\s*>\s?/, '')); });
        box.append(quote);
      } else if (ITEM.test(line)) {
        const ordered = /^\s*\d/.test(line);
        box.append(list(take(row => ITEM.test(row) && /^\s*\d/.test(row) === ordered), ordered));
      } else if (line.includes('|') && (lines[i + 1] || '').includes('-') && SEPARATOR.test(lines[i + 1])) {
        box.append(table(take(row => row.includes('|'))));
      } else {
        const p = el('p');
        i++;
        [line].concat(take(row => row.trim() && !/^\s*(```|#{1,4}\s|>)/.test(row) && !ITEM.test(row)))
          .forEach((row, n) => { if (n) p.append(el('br')); inline(p, row.trim()); });
        box.append(p);
      }
    }
    return box;
  }

  // ---- conteúdo -----------------------------------------------------------
  function content(body, format) {
    const lines = String(body || '').split('\n').map(s => s.trim()).filter(Boolean);
    if (format === 'lista') return list(lines, false);
    if (format === 'tabela') return table(lines);
    return rich(body);
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
    const mark = el('span', 'card-icon'); mark.setAttribute('aria-hidden', 'true');
    head.append(mark, el('span', 'card-title', event.text || ''));
    if (event.ok === false) head.append(el('span', 'card-flag', 'Falhou'));
    node.append(head);
    if (kind === 'weather' && event.weather && typeof event.weather === 'object') node.append(weather(event.weather));
    if (event.body) node.append(kind === 'content' ? content(event.body, event.format) : inline(el('p', 'card-body'), event.body));
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
  /* Barrinha de tempo: encolhe por `ms` e, ao zerar, chama `done`. É a própria animação que
     marca o tempo, então pausar com o mouse em cima (no CSS) também adia a saída do cartão. */
  function life(node, ms, done) {
    const track = el('div', 'card-life'), fill = el('i');
    track.setAttribute('aria-hidden', 'true');
    fill.style.animationDuration = ms + 'ms';
    fill.addEventListener('animationend', done);
    track.append(fill);
    node.append(track);
  }

  function show(event) {
    const kind = KINDS[event.kind] ? event.kind : 'action';
    const node = build(event, kind);
    if (PANEL_KINDS[kind]) {
      closePanel();
      node.classList.add('panel');
      const close = el('button', 'panel-close', '×');
      close.type = 'button'; close.setAttribute('aria-label', 'Fechar painel');
      close.addEventListener('click', closePanel);
      node.querySelector('.card-head').append(close);
      panel = { el: node };
      layer.prepend(node);
      life(node, PANEL_LIFE, () => { if (panel && panel.el === node) closePanel(); });
      stack();
    } else {
      node.classList.add('toast');
      const limit = narrow() ? 3 : TOASTS;
      while (toasts.length >= limit) removeToast(toasts[0]);
      const card = { el: node };
      toasts.push(card);
      // notificação de mensagem do WhatsApp: clicar abre a conversa
      if (/^[0-9A-Za-z.:_-]{3,40}@(s\.whatsapp\.net|lid)$/.test(event.wa || '') && window.VivWhatsApp) {
        node.classList.add('clickable');
        node.setAttribute('role', 'button'); node.tabIndex = 0;
        node.setAttribute('aria-label', (event.text || 'WhatsApp') + ': abrir a conversa');
        const go = () => { window.VivWhatsApp.open({ jid: event.wa }); removeToast(card); };
        node.addEventListener('click', go);
        node.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
      }
      layer.append(node);
      placeToasts();                                   // depois de entrar na página, quando já tem altura
      life(node, TOAST_LIFE, () => removeToast(card));
    }
    node.querySelectorAll('.result, li, tr, .weather-stat, .weather-day, .md > *').forEach((item, i) => item.style.setProperty('--i', Math.min(i, 24)));
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
    placeToasts(); drawLinks();
  };
  window.addEventListener('resize', relayout);
  window.addEventListener('viv-core-moved', drawLinks);
  window.VivCards = { show, confirm, confirmDone, hint, closePanel, stack };
})();
