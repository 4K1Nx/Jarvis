/* WhatsApp na HUD.
   - Destaque: enquanto a Viv fala de uma pessoa, aparece só o contato e a mensagem dela, um por vez.
   - Painel geral: quando ela termina de falar, todas as conversas recentes, com as pendentes marcadas.
   - Conversa: um chat aberto, com balões, fotos e áudios.
   Todo texto entra por textContent. Imagens só entram se forem miniaturas embutidas (data:image) ou
   fotos de perfil em https; qualquer outro endereço é ignorado. */
(function () {
  'use strict';
  const root = document.getElementById('wa');
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const fold = text => String(text || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const THUMB = /^data:image\/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$/;
  const PHOTO = /^https:\/\/[a-z0-9.-]+\.(whatsapp\.net|fbcdn\.net)\//i;
  let queue = null;          // conversas da última listagem, à espera de serem faladas
  let shown = new Set();     // quais já ganharam destaque
  let timer = null;

  function avatar(name, photo) {
    const box = el('span', 'wa-avatar', (String(name || '?').trim()[0] || '?').toUpperCase());
    if (PHOTO.test(photo || '')) {
      const img = el('img');
      img.alt = ''; img.referrerPolicy = 'no-referrer';
      img.addEventListener('load', () => { box.textContent = ''; box.append(img); });
      img.src = photo;
    }
    return box;
  }

  function clear(now) {
    clearTimeout(timer); timer = null;
    const old = [...root.children];
    old.forEach(node => { node.classList.remove('in'); node.classList.add('out'); });
    setTimeout(() => old.forEach(node => node.remove()), now ? 0 : 420);
  }

  function mount(node, life) {
    clear();
    if (window.VivCards) window.VivCards.closePanel();
    root.append(node);
    requestAnimationFrame(() => requestAnimationFrame(() => node.classList.add('in')));
    timer = setTimeout(() => clear(), life);
  }

  function head(name, photo, unread, close) {
    const box = el('header', 'wa-head');
    const text = el('div', 'wa-who');
    text.append(el('b', null, name));
    if (unread) text.append(el('small', null, unread === 1 ? '1 mensagem nova' : `${unread} mensagens novas`));
    box.append(avatar(name, photo), text);
    if (close) {
      const button = el('button', 'wa-close', '×');
      button.type = 'button'; button.setAttribute('aria-label', 'Fechar');
      button.addEventListener('click', () => clear());
      box.append(button);
    }
    return box;
  }

  // ---- destaque: uma pessoa por vez -------------------------------------------------
  function spotlight(chat) {
    const card = el('article', 'wa-card wa-spot');
    card.setAttribute('aria-label', `Mensagem de ${chat.label}`);
    card.append(head(chat.label, chat.photo, chat.unread), el('p', 'wa-bubble in', chat.last || 'Sem prévia da mensagem.'));
    mount(card, 20000);
  }

  // ---- painel geral -------------------------------------------------------------------
  function overview(chats) {
    const pending = chats.filter(c => c.unread).length;
    const card = el('article', 'wa-card wa-list');
    card.setAttribute('aria-label', 'Conversas do WhatsApp');
    const top = el('header', 'wa-head');
    const title = el('div', 'wa-who');
    title.append(el('b', null, 'WhatsApp'), el('small', null, pending ? (pending === 1 ? '1 conversa pendente' : `${pending} conversas pendentes`) : 'Nada pendente'));
    const close = el('button', 'wa-close', '×');
    close.type = 'button'; close.setAttribute('aria-label', 'Fechar');
    close.addEventListener('click', () => clear());
    top.append(el('span', 'wa-logo', '✆'), title, close);
    const list = el('ul', 'wa-rows');
    chats.forEach((chat, i) => {
      const row = el('li', 'wa-row');
      row.style.setProperty('--i', Math.min(i, 14));
      if (chat.unread) row.dataset.pending = 'true';
      const text = el('div', 'wa-row-text');
      text.append(el('b', null, chat.label), el('span', null, chat.last || ''));
      row.append(avatar(chat.label, chat.photo), text);
      if (chat.unread) row.append(el('i', 'wa-badge', String(chat.unread)));
      list.append(row);
    });
    card.append(top, list, el('p', 'wa-foot', pending ? 'Diga “responde a…” ou “abre a conversa de…”.' : 'Diga “abre a conversa de…” para ver uma delas.'));
    mount(card, 90000);
  }

  // ---- conversa aberta ------------------------------------------------------------------
  function chat(event) {
    const card = el('article', 'wa-card wa-chat');
    card.setAttribute('aria-label', `Conversa com ${event.text}`);
    const body = el('div', 'wa-thread');
    (event.messages || []).forEach((m, i) => {
      const bubble = el('div', 'wa-bubble ' + (m.out ? 'out' : 'in'));
      bubble.style.setProperty('--i', Math.min(i, 20));
      if (!m.out && m.autor && m.autor !== 'Contato' && m.autor !== event.contact) bubble.append(el('b', 'wa-author', m.autor));
      if (THUMB.test(m.imagem || '')) { const img = el('img', 'wa-photo'); img.alt = 'Foto'; img.src = m.imagem; bubble.append(img); }
      if (m.audio) bubble.append(el('span', 'wa-audio', '▶  Áudio'));
      if (m.texto) bubble.append(el('span', 'wa-text', m.texto));
      if (!m.texto && !m.audio && !bubble.querySelector('img')) bubble.append(el('span', 'wa-text wa-muted', 'Mídia'));
      if (m.hora) bubble.append(el('time', null, m.hora));
      body.append(bubble);
    });
    if (!body.children.length) body.append(el('p', 'wa-foot', 'Nenhuma mensagem visível.'));
    card.append(head(event.text, event.photo, 0, true), body);
    mount(card, 120000);
    requestAnimationFrame(() => { body.scrollTop = body.scrollHeight; });
  }

  // ---- conectar o WhatsApp: QR code ou código ------------------------------------------------
  const QR = /^data:image\/png;base64,[A-Za-z0-9+/=]+$/;

  function connect(event) {
    const current = root.querySelector('.wa-connect.in');
    if (current && event.qr && QR.test(event.qr)) {          // QR renovado: troca só a imagem
      const img = current.querySelector('.wa-qr');
      if (img) { img.src = event.qr; return; }
    }
    const card = el('article', 'wa-card wa-connect');
    card.setAttribute('aria-label', 'Conectar WhatsApp');
    card.append(head('Conectar WhatsApp', '', 0, true));
    const body = el('div', 'wa-connect-body');
    if (event.qr && QR.test(event.qr)) {
      const img = el('img', 'wa-qr'); img.alt = 'QR code para conectar o WhatsApp'; img.src = event.qr;
      body.append(img, el('p', null, 'No celular: WhatsApp › Aparelhos conectados › Conectar aparelho, e aponte para cá.'));
    } else if (/^[A-Z0-9-]{6,12}$/i.test(event.code || '')) {
      body.append(el('p', 'wa-code', event.code),
        el('p', null, 'No celular: WhatsApp › Aparelhos conectados › Conectar aparelho › Conectar com número de telefone.'));
    } else {
      return;
    }
    card.append(body);
    mount(card, 180000);
  }

  // ---- ligação com a fala da Viv ----------------------------------------------------------
  function handle(event) {
    if (event.mode === 'conectar') { queue = null; connect(event); return; }
    if (event.mode === 'conectado') { clear(); return; }
    if (event.mode === 'chat') { queue = null; chat(event); return; }
    if (event.mode !== 'lista') return;
    queue = Array.isArray(event.chats) ? event.chats : [];
    shown = new Set();
    clear();
    if (!queue.length) queue = null;
  }

  // A cada trecho que a Viv fala: se ela acabou de citar alguém da lista, essa pessoa entra em destaque.
  function heard(text) {
    if (!queue) return;
    const said = fold(text);
    let latest = null, position = -1;
    for (const item of queue) {
      const label = fold(item.label), first = label.split(' ')[0];
      const unique = queue.filter(other => fold(other.label).split(' ')[0] === first).length === 1;
      const at = Math.max(said.lastIndexOf(label), unique && first.length >= 3 ? said.lastIndexOf(first) : -1);
      if (at > position) { position = at; latest = item; }
    }
    if (latest && !shown.has(latest.name)) { shown.add(latest.name); spotlight(latest); }
  }

  // Ela terminou de falar: abre o painel com todas.
  function turnEnd() {
    if (!queue) return;
    const chats = queue;
    queue = null;
    overview(chats);
  }

  window.VivWhatsApp = { handle, heard, turnEnd, close: () => { queue = null; clear(); } };
})();
