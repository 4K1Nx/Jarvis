/* Avisos (toasts): o cartãozinho do canto superior direito, usado pela HUD (cards.js) e pela janelinha de avisos
   da miniatura (avisos.js). Cada aviso tem uma imagem à esquerda — a foto de quem mandou a mensagem, a capa do
   álbum que começou a tocar, ou um ícone do tipo do aviso — e, à direita, a origem, o título e o texto.
   Imagens só entram de endereços https conhecidos (WhatsApp, capas de álbum); texto entra por textContent. */
(function () {
  'use strict';
  const IMAGE = /^https:\/\/([a-z0-9-]+\.)*(whatsapp\.net|fbcdn\.net|mzstatic\.com|scdn\.co|spotifycdn\.com)\/[^\s"'()<>\\]*$/i;
  const NS = 'http://www.w3.org/2000/svg';
  const ICONS = {
    done: ['M5 12.5l4.5 4.5L19 7.5'],
    info: ['M12 11v6', 'M12 7.6v.1', 'circle:12,12,9'],
    alert: ['M12 7.5v6', 'M12 16.6v.1', 'M10.3 3.9L2.6 17.5A2 2 0 004.3 20.5h15.4a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z'],
    music: ['M9 18V6l10-2v12', 'circle:6.5,18,2.5', 'circle:16.5,16,2.5'],
    chat: ['M20 12a8 8 0 01-11.6 7.1L4 20l1-4.2A8 8 0 1120 12z'],
    task: ['M12 3v3', 'M12 18v3', 'M3 12h3', 'M18 12h3', 'M5.6 5.6l2.1 2.1', 'M16.3 16.3l2.1 2.1', 'M5.6 18.4l2.1-2.1', 'M16.3 7.7l2.1-2.1'],
  };
  const SOURCES = { action: 'Feito', data: 'Aviso', music: 'Tocando agora', wa: 'WhatsApp', fail: 'Não deu certo' };

  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };

  function icon(name) {
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    for (const part of ICONS[name] || ICONS.info) {
      let shape;
      if (part.startsWith('circle:')) {
        const [cx, cy, r] = part.slice(7).split(',');
        shape = document.createElementNS(NS, 'circle');
        shape.setAttribute('cx', cx); shape.setAttribute('cy', cy); shape.setAttribute('r', r);
      } else {
        shape = document.createElementNS(NS, 'path');
        shape.setAttribute('d', part);
      }
      svg.append(shape);
    }
    return svg;
  }

  // Qual é o aviso: decide a cor, o ícone e a origem mostrada em cima do título.
  function flavor(event) {
    if (event.ok === false) return 'fail';
    if (event.kind === 'music') return 'music';
    if (event.wa) return 'wa';
    return event.kind === 'data' ? 'data' : 'action';
  }

  function media(event, kind) {
    const box = el('div', 'toast-media');
    const fallback = kind === 'wa'
      ? el('span', 'toast-initial', (String(event.text || '').replace(/^WhatsApp:\s*/i, '').trim()[0] || '?').toUpperCase())
      : icon({ fail: 'alert', music: 'music', wa: 'chat', data: 'info' }[kind] || 'done');
    box.append(fallback);
    const src = event.image || event.photo;
    if (IMAGE.test(src || '')) {
      const img = el('img');
      img.alt = ''; img.referrerPolicy = 'no-referrer'; img.decoding = 'async';
      img.addEventListener('load', () => { fallback.remove(); box.classList.add('has-image'); });
      img.addEventListener('error', () => img.remove());
      img.src = src;
      box.append(img);
    }
    if (kind === 'music') {
      const bars = el('span', 'toast-eq'); bars.setAttribute('aria-hidden', 'true');
      for (let i = 0; i < 4; i++) bars.append(el('i'));
      box.append(bars);
    }
    return box;
  }

  /* O cartão do aviso, sem posição nem tempo de vida (isso é de quem o mostra). `inline(target, text)` aplica a
     formatação simples do corpo; sem ela, o corpo entra como texto puro. */
  function build(event, inline) {
    const kind = flavor(event);
    const node = el('article', 'card toast');
    node.dataset.kind = event.kind === 'music' ? 'music' : event.kind === 'data' ? 'data' : 'action';
    node.dataset.flavor = kind;
    node.dataset.ok = event.ok === false ? 'false' : 'true';
    const src = event.image || event.photo;
    if (kind === 'music' && IMAGE.test(src || '')) node.style.setProperty('--art', `url("${src}")`);
    const row = el('div', 'toast-row');
    const text = el('div', 'toast-text');
    const meta = el('div', 'toast-meta');
    meta.append(el('span', 'toast-source', event.source || SOURCES[kind]),
                el('time', 'toast-time', new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })));
    let title = String(event.text || '');
    if (kind === 'wa') title = title.replace(/^WhatsApp:\s*/i, '');
    text.append(meta, el('div', 'card-title', title));
    if (event.body) {
      const body = el('p', 'card-body');
      if (inline) inline(body, String(event.body)); else body.textContent = String(event.body);
      text.append(body);
    }
    row.append(media(event, kind), text);
    node.append(row);
    return node;
  }

  window.VivToast = { build, IMAGE };
})();
