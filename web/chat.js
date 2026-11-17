/* Chat de texto: conversar digitando, com a Viv ou direto com um modelo instalado no Ollama.
   Com a Viv, as mensagens digitadas chegam a ela como fala do usuário e um seletor escolhe entre “só texto” (ela
   não fala em voz alta e o microfone fica fechado) e “texto e voz”. Com um modelo local, a conversa é só por
   escrito, a Viv não participa e cada modelo tem a própria conversa. Todo texto entra por textContent. */
(function () {
  'use strict';
  const box = document.getElementById('chat');
  if (!box) return;
  const list = document.getElementById('chat-list'), form = document.getElementById('chat-form');
  const input = document.getElementById('chat-input'), toggle = document.getElementById('chat-open');
  const picker = document.getElementById('chat-model'), fresh = document.getElementById('chat-new');
  const modes = [...box.querySelectorAll('[data-mode]')];
  const MAX = 80;
  const logs = { viv: [] };             // modelo -> [{ role, text, failed }]
  let model = 'viv';
  const live = {};                      // modelo -> resposta que ainda está sendo escrita
  let textOnly = false;

  const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

  function draw(entry) {
    const node = document.createElement('div');
    node.className = 'chat-msg ' + entry.role + (entry.failed ? ' failed' : '');
    node.textContent = entry.text;
    entry.node = node;
    list.append(node);
    list.scrollTop = list.scrollHeight;
  }

  function add(to, role, text) {
    const log = logs[to] || (logs[to] = []);
    const entry = { role, text };
    log.push(entry);
    while (log.length > MAX) { const old = log.shift(); if (old.node) old.node.remove(); }
    if (to === model) draw(entry);
    return entry;
  }

  function rewrite(entry, text) {
    entry.text = text;
    if (entry.node) { entry.node.textContent = text; list.scrollTop = list.scrollHeight; }
  }

  function render() {
    list.textContent = '';
    (logs[model] || []).forEach(entry => { entry.node = null; draw(entry); });
    const local = model !== 'viv';
    fresh.hidden = !local;
    modes.forEach(button => { button.disabled = local; });
    box.dataset.local = local ? 'true' : 'false';
    input.placeholder = local ? 'Escreva para ' + model.split(':')[0] + '…' : 'Escreva para a Viv…';
  }

  function showMode(on) {
    textOnly = !!on;
    document.body.dataset.textOnly = textOnly ? 'true' : 'false';
    modes.forEach(button => button.setAttribute('aria-pressed', String((button.dataset.mode === 'texto') === textOnly)));
  }

  function setMode(on) {
    showMode(on);
    post('/api/chat/modo', { so_texto: textOnly }).catch(() => {});
  }

  function choose(next) {
    model = [...picker.options].some(option => option.value === next) ? next : 'viv';
    picker.value = model;
    try { localStorage.setItem('viv-chat-modelo', model); } catch (error) { /* sem armazenamento, só não lembra */ }
    if (model !== 'viv' && textOnly) setMode(false);       // o modo só texto é da Viv; com outro modelo ela volta ao normal
    render();
  }

  async function loadModels() {
    try {
      const data = await (await fetch('/api/chat/modelos')).json();
      picker.textContent = '';
      (data.modelos || []).forEach(item => {
        const option = document.createElement('option');
        option.value = item.id; option.textContent = item.nome;
        picker.append(option);
      });
    } catch (error) { /* sem a lista, fica só a Viv */ }
    let saved = 'viv';
    try { saved = localStorage.getItem('viv-chat-modelo') || 'viv'; } catch (error) { /* idem */ }
    choose(saved);
  }

  function open() {
    if (!box.hidden) return;
    box.hidden = false;
    document.body.classList.add('chat-open');
    toggle.setAttribute('aria-expanded', 'true');
    loadModels();
    input.focus();
  }

  function close() {
    if (box.hidden) return;
    box.hidden = true;
    document.body.classList.remove('chat-open');
    toggle.setAttribute('aria-expanded', 'false');
    if (textOnly) setMode(false);       // fechar o chat devolve a voz a ela
  }

  function send() {
    const local = model !== 'viv';
    const text = local ? input.value.trim() : input.value.replace(/\s+/g, ' ').trim();
    if (!text) return;
    input.value = '';
    const mine = add(model, 'user', text), to = model;
    // o balão de espera entra já: uma resposta rápida pode chegar antes de o envio confirmar
    const waiting = local && !live[to] ? (live[to] = add(to, 'viv', '…')) : null;
    post('/api/chat', { texto: text, modelo: to }).then(reply => {
      if (reply.status === 409) throw new Error('Espere a resposta anterior terminar.');
      if (!reply.ok) throw new Error('Não foi enviada. Tente de novo.');
    }).catch(error => {
      mine.failed = true;
      if (mine.node) { mine.node.classList.add('failed'); mine.node.title = error.message; }
      if (waiting && live[to] === waiting) {
        delete live[to];
        logs[to] = logs[to].filter(entry => entry !== waiting);
        if (waiting.node) waiting.node.remove();
      }
    });
  }

  form.addEventListener('submit', event => { event.preventDefault(); send(); });
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); }
    if (event.key === 'Escape') close();
  });
  toggle.addEventListener('click', () => (box.hidden ? open() : close()));
  document.getElementById('chat-close').addEventListener('click', close);
  modes.forEach(button => button.addEventListener('click', () => setMode(button.dataset.mode === 'texto')));
  picker.addEventListener('change', () => choose(picker.value));
  fresh.addEventListener('click', () => {
    if (model === 'viv') return;
    logs[model] = [];
    delete live[model];
    post('/api/chat/nova', { modelo: model }).catch(() => {});
    render();
  });

  window.VivChat = {
    // falas da conversa com a Viv: as do usuário entram quando fecham; a dela vai sendo reescrita até fechar
    transcript(event) {
      const text = String(event.text || '').trim();
      if (!text) return;
      if (event.role === 'user') {
        if (event.final && !event.typed) add('viv', 'user', text);     // a digitada já está na lista
        return;
      }
      if (!live.viv) live.viv = add('viv', 'viv', text); else rewrite(live.viv, text);
      if (event.final) delete live.viv;
    },
    handle(event) {
      if (event.reply) {                                               // resposta de um modelo local
        const to = String(event.model || ''), text = String(event.text || '');
        if (!live[to]) live[to] = add(to, 'viv', text); else rewrite(live[to], text);
        if (event.failed) { live[to].failed = true; if (live[to].node) live[to].node.classList.add('failed'); }
        if (event.final) delete live[to];
        return;
      }
      if (typeof event.text_only === 'boolean') showMode(event.text_only);
      if (event.open) open();
    },
    open, close,
  };
})();
