/* WhatsApp na HUD.
   - Destaque: enquanto a Viv fala de uma pessoa, aparece só aquela conversa e as mensagens novas dela.
   - Painel geral: quando ela termina de falar, todas as conversas recentes, com as pendentes marcadas.
     Clicar numa conversa abre essa conversa.
   - Conversa: um chat aberto, com balões, fotos e áudios; em grupos, cada mensagem diz quem mandou.
     Um áudio pode ser tocado nas caixas de som ou transcrito; a transcrição aparece embaixo dele.
   A legenda que chega aqui já acompanha o áudio que está tocando (viv/live.py), então o destaque
   segue a fala. Todo texto entra por textContent. Imagens só entram se forem miniaturas embutidas
   (data:image) ou fotos de perfil do WhatsApp em https; qualquer outro endereço é ignorado. */
(function () {
  'use strict';
  const root = document.getElementById('wa');
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const words = text => ' ' + String(text || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ').trim() + ' ';
  // palavras que sozinhas não identificam ninguém
  const VAGUE = new Set(['a', 'o', 'as', 'os', 'de', 'da', 'do', 'e', 'meu', 'minha', 'seu', 'sua', 'grupo', 'amigo', 'amiga', 'tia', 'tio']);
  const THUMB = /^data:image\/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$/;
  const PHOTO = /^https:\/\/[a-z0-9.-]+\.(whatsapp\.net|fbcdn\.net)\//i;
  let queue = null;          // conversas da última listagem, à espera de serem faladas
  let current = null;        // conversa em destaque agora
  let timer = null;

  function avatar(name, photo, group) {
    const box = el('span', 'wa-avatar', (String(name || '?').trim()[0] || '?').toUpperCase());
    if (group) box.classList.add('wa-group');
    if (PHOTO.test(photo || '')) {
      const img = el('img');
      img.alt = ''; img.referrerPolicy = 'no-referrer';
      img.addEventListener('load', () => { box.textContent = ''; box.append(img); });
      img.src = photo;
    }
    return box;
  }

  // balão de conversa desenhado em SVG: os símbolos de telefone das fontes variam de máquina para máquina
  function logo() {
    const ns = 'http://www.w3.org/2000/svg', box = el('span', 'wa-logo'), svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('width', '18'); svg.setAttribute('height', '18'); svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS(ns, 'path');
    path.setAttribute('d', 'M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.2 3.6c-.5.4-1.3.1-1.3-.6V16A2.5 2.5 0 0 1 4 13.5z');
    path.setAttribute('fill', 'none'); path.setAttribute('stroke', 'currentColor'); path.setAttribute('stroke-width', '1.6'); path.setAttribute('stroke-linejoin', 'round');
    svg.append(path); box.append(svg);
    return box;
  }

  function clear(now) {
    clearTimeout(timer); timer = null;
    const old = [...root.children];
    old.forEach(node => { node.classList.remove('in'); node.classList.add('out'); });
    setTimeout(() => { old.forEach(node => node.remove()); if (window.VivCards) window.VivCards.stack(); }, now ? 0 : 420);
  }

  function mount(node, life) {
    clear();
    root.append(node);
    if (window.VivCards) window.VivCards.stack();       // com um rascunho aberto, a conversa vai para baixo dele
    requestAnimationFrame(() => requestAnimationFrame(() => node.classList.add('in')));
    timer = setTimeout(() => clear(), life);
  }

  function head(name, photo, note, close, group) {
    const box = el('header', 'wa-head');
    const text = el('div', 'wa-who');
    text.append(el('b', null, name));
    if (note) text.append(el('small', null, note));
    box.append(avatar(name, photo, group), text);
    if (close) {
      const button = el('button', 'wa-close', '×');
      button.type = 'button'; button.setAttribute('aria-label', 'Fechar');
      button.addEventListener('click', () => clear());
      box.append(button);
    }
    return box;
  }

  const newCount = n => (n === 1 ? '1 mensagem nova' : `${n} mensagens novas`);
  const AUDIO_ID = /^[A-Za-z0-9_-]{6,80}$/;
  let chatJid = '';          // conversa aberta agora: os botões dos áudios agem nela

  // Áudio na conversa: ▶ toca nas caixas de som; “Transcrever” mostra o que foi dito logo abaixo.
  function audioBox(message) {
    const box = el('div', 'wa-audio');
    box.dataset.id = message.id || '';
    const text = el('p', 'wa-heard', message.transcricao || '');
    const usable = chatJid && AUDIO_ID.test(message.id || '');
    const call = (acao, button, busy) => {
      const label = button.textContent;
      button.disabled = true; button.textContent = busy;
      return fetch('/api/whatsapp/audio', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jid: chatJid, id: message.id, acao }) })
        .then(r => r.json().then(data => ({ ok: r.ok, data })))
        .then(({ ok, data }) => {
          if (!ok) { text.textContent = (data && data.detail) || 'Não consegui agora.'; text.classList.add('wa-muted'); }
          else if (acao === 'transcrever') { text.textContent = data.transcricao || '(sem fala que eu entendesse)'; text.classList.remove('wa-muted'); }
        })
        .catch(() => { text.textContent = 'Sem contato com a Viv.'; })
        .finally(() => { button.disabled = false; button.textContent = label; });
    };
    const play = el('button', 'wa-play', '▶  Áudio');
    play.type = 'button'; play.setAttribute('aria-label', 'Tocar o áudio nas caixas de som');
    box.append(play);
    if (usable) {
      play.addEventListener('click', () => call('tocar', play, '♪  Tocando'));
      if (!message.transcricao) {
        const read = el('button', 'wa-transcribe', 'Transcrever');
        read.type = 'button';
        read.addEventListener('click', () => call('transcrever', read, 'Ouvindo…').then(() => { if (text.textContent) read.remove(); }));
        box.append(read);
      }
    } else {
      play.disabled = true; play.title = 'Peça à Viv para ouvir este áudio';
    }
    box.append(text);
    return box;
  }

  // A Viv transcreveu um áudio (pelo clique ou por pedido de voz): aparece na conversa aberta.
  function transcription(event) {
    if (!AUDIO_ID.test(event.id || '')) return;
    root.querySelectorAll('.wa-audio').forEach(box => {
      if (box.dataset.id !== event.id) return;
      const text = box.querySelector('.wa-heard');
      if (text) { text.textContent = event.transcricao || ''; text.classList.remove('wa-muted'); }
      const read = box.querySelector('.wa-transcribe');
      if (read) read.remove();
    });
  }

  function bubble(message, showAuthor, index) {
    const node = el('div', 'wa-bubble ' + (message.out ? 'out' : 'in'));
    node.style.setProperty('--i', Math.min(index, 20));
    if (showAuthor && !message.out && message.autor) node.append(el('b', 'wa-author', message.autor));
    if (THUMB.test(message.imagem || '')) { const img = el('img', 'wa-photo'); img.alt = 'Foto'; img.src = message.imagem; node.append(img); }
    if (message.audio) node.append(audioBox(message));
    if (message.texto) node.append(el('span', 'wa-text', message.texto));
    if (!message.texto && !message.audio && !node.querySelector('img')) node.append(el('span', 'wa-text wa-muted', 'Mídia'));
    if (message.hora) node.append(el('time', null, message.hora));
    return node;
  }

  // ---- destaque: a conversa de que ela está falando ------------------------------------------
  function spotlight(chat) {
    const card = el('article', 'wa-card wa-spot');
    card.setAttribute('aria-label', `Conversa: ${chat.label}`);
    const note = chat.unread ? newCount(chat.unread) : chat.mine ? 'Você mandou a última mensagem' : (chat.group ? 'Grupo' : '');
    card.append(head(chat.label, chat.photo, note, false, chat.group));
    const body = el('div', 'wa-thread');
    const messages = Array.isArray(chat.novas) ? chat.novas : [];
    if (messages.length) messages.forEach((m, i) => body.append(bubble(m, chat.group, i)));
    else body.append(bubble({ out: !!chat.mine, texto: chat.preview || chat.last || 'Sem prévia da mensagem.' }, false, 0));
    card.append(body);
    mount(card, 25000);
  }

  // ---- painel geral -----------------------------------------------------------------------
  // Abre a conversa na tela: pelo nome (lista) ou pelo número (clique numa notificação).
  function open(chat) {
    fetch('/api/whatsapp/abrir', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ contato: chat.jid || chat.name }) })
      .catch(() => {});
  }

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
    top.append(logo(), title, close);
    const list = el('ul', 'wa-rows');
    chats.forEach((chat, i) => {
      const row = el('li', 'wa-row');
      row.style.setProperty('--i', Math.min(i, 14));
      if (chat.unread) row.dataset.pending = 'true';
      const button = el('button', 'wa-row-open');
      button.type = 'button'; button.setAttribute('aria-label', `Abrir a conversa: ${chat.label}`);
      const text = el('div', 'wa-row-text');
      text.append(el('b', null, chat.label), el('span', null, chat.last || ''));
      button.append(avatar(chat.label, chat.photo, chat.group), text);
      if (chat.unread) button.append(el('i', 'wa-badge', String(chat.unread)));
      button.addEventListener('click', () => open(chat));
      row.append(button);
      list.append(row);
    });
    card.append(top, list, el('p', 'wa-foot', 'Clique numa conversa para abrir, ou diga “responde a…”.'));
    mount(card, 90000);
  }

  // ---- conversa aberta ------------------------------------------------------------------------
  function chat(event) {
    chatJid = /^[0-9A-Za-z.:_-]{3,40}@(s\.whatsapp\.net|g\.us|lid)$/.test(event.jid || '') ? event.jid : '';
    const card = el('article', 'wa-card wa-chat');
    card.setAttribute('aria-label', `Conversa com ${event.text}`);
    const body = el('div', 'wa-thread');
    (event.messages || []).forEach((m, i) => body.append(bubble(m, !!event.group, i)));
    if (!body.children.length) body.append(el('p', 'wa-foot', 'Nenhuma mensagem visível.'));
    card.append(head(event.text, event.photo, event.group ? 'Grupo' : '', true, !!event.group), body);
    mount(card, 120000);
    requestAnimationFrame(() => { body.scrollTop = body.scrollHeight; });
  }

  // ---- conectar o WhatsApp: QR code ou código ------------------------------------------------
  const QR = /^data:image\/png;base64,[A-Za-z0-9+/=]+$/;

  function connect(event) {
    const shown = root.querySelector('.wa-connect.in');
    if (shown && event.qr && QR.test(event.qr)) {          // QR renovado: troca só a imagem
      const img = shown.querySelector('.wa-qr');
      if (img) { img.src = event.qr; return; }
    }
    const card = el('article', 'wa-card wa-connect');
    card.setAttribute('aria-label', 'Conectar WhatsApp');
    card.append(head('Conectar WhatsApp', '', '', true));
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

  // ---- ligação com a fala da Viv -------------------------------------------------------------
  function handle(event) {
    if (event.mode === 'conectar') { queue = null; connect(event); return; }
    if (event.mode === 'conectado') { clear(); return; }
    if (event.mode === 'transcricao') { transcription(event); return; }
    if (event.mode === 'chat') { queue = null; chat(event); return; }
    if (event.mode !== 'lista') return;
    queue = Array.isArray(event.chats) && event.chats.length ? event.chats : null;
    current = null;
    clear();
  }

  // Os nomes pelos quais ela pode se referir a uma conversa, como palavras inteiras.
  function names(item) {
    const list = Array.isArray(item.aliases) && item.aliases.length ? item.aliases : [item.label];
    return list.map(words).filter(w => w.trim() && !(w.trim().split(' ').length === 1 && VAGUE.has(w.trim())));
  }

  // A cada trecho falado: a conversa citada por último, como palavra inteira, entra em destaque.
  function heard(text) {
    if (!queue) return;
    const said = words(text);
    let latest = null, position = -1, size = 0;
    for (const item of queue) {
      for (const name of names(item)) {
        const at = said.lastIndexOf(name);
        // empate na mesma posição ("Maria" e "Maria Silva"): vale o nome mais completo
        if (at > position || (at >= 0 && at === position && name.length > size)) { position = at; size = name.length; latest = item; }
      }
    }
    if (latest && latest !== current) { current = latest; spotlight(latest); }
  }

  // Ela terminou de falar: abre o painel com todas.
  function turnEnd() {
    if (!queue) return;
    const chats = queue;
    queue = null; current = null;
    overview(chats);
  }

  window.VivWhatsApp = { handle, heard, turnEnd, open, close: () => { queue = null; current = null; clear(); } };
})();
