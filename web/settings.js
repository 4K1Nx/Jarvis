/* Tela de configurações: lê o esquema do servidor e monta os campos. Um ajuste novo
   no servidor aparece aqui sem mudar este arquivo. */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const drawer = $('settings'), gear = $('gear');
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  let closing = null;

  function message(text, bad) {
    const node = $('settings-msg');
    node.textContent = text || '';
    node.classList.toggle('bad', !!bad);
  }

  async function send(url, method, body) {
    const response = await fetch(url, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Não foi possível salvar.');
    return data;
  }

  async function save(key, value, label) {
    try {
      await send('/api/settings', 'POST', { key, value });
      message(`${label}: salvo.`);
    } catch (error) {
      message(error.message, true);
      load();
    }
  }

  function field(item) {
    const row = el('label', 'setting');
    const text = el('span', 'setting-text');
    text.append(el('b', null, item.label));
    if (item.description) text.append(el('small', null, item.description));
    let input;
    if (item.type === 'bool') {
      input = el('input'); input.type = 'checkbox'; input.checked = !!item.value; input.className = 'switch';
      input.addEventListener('change', () => save(item.key, input.checked, item.label));
    } else {
      input = el('input');
      input.type = item.type === 'text' ? 'text' : 'number';
      if (item.type === 'float') input.step = '0.01';
      input.value = item.value;
      input.addEventListener('change', () => save(item.key, input.value, item.label));
    }
    input.dataset.key = item.key;
    row.append(text, input);
    return row;
  }

  function routine(list) {
    const box = $('routine-list');
    while (box.firstChild) box.firstChild.remove();
    if (!list.length) box.append(el('p', 'routine-empty', 'Nenhum item. Conte sua rotina à Viv ou adicione abaixo.'));
    list.forEach(item => {
      const row = el('div', 'routine-row');
      const remove = el('button', 'routine-remove', '×');
      remove.type = 'button'; remove.setAttribute('aria-label', `Remover ${item.texto}`);
      remove.addEventListener('click', async () => {
        try { routine((await send('/api/routine/' + encodeURIComponent(item.id), 'DELETE')).rotina); message('Item removido.'); }
        catch (error) { message(error.message, true); }
      });
      row.append(el('b', null, item.hora), el('span', null, item.texto), el('small', null, item.dias_texto), remove);
      box.append(row);
    });
  }

  async function load() {
    try {
      const data = await (await fetch('/api/settings')).json();
      const list = $('settings-list');
      while (list.firstChild) list.firstChild.remove();
      (data.items || []).forEach((item, i) => { const row = field(item); row.style.setProperty('--i', i); list.append(row); });
      routine(data.rotina || []);
    } catch (error) { message('Configurações indisponíveis.', true); }
  }

  function open() {
    clearTimeout(closing);
    drawer.hidden = false;
    gear.setAttribute('aria-expanded', 'true');
    requestAnimationFrame(() => drawer.classList.add('open'));
    message('');
    load();
  }

  function close() {
    drawer.classList.remove('open');
    gear.setAttribute('aria-expanded', 'false');
    closing = setTimeout(() => { drawer.hidden = true; }, 380);
  }

  gear.addEventListener('click', () => (drawer.classList.contains('open') ? close() : open()));
  $('settings-close').addEventListener('click', close);
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && drawer.classList.contains('open')) close(); });
  $('routine-form').addEventListener('submit', async event => {
    event.preventDefault();
    try {
      const data = await send('/api/routine', 'POST', { hora: $('routine-time').value, texto: $('routine-text').value, dias: $('routine-days').value });
      routine(data.rotina); $('routine-text').value = ''; message('Item adicionado à rotina.');
    } catch (error) { message(error.message, true); }
  });
  window.VivSettings = { open, close, load };
})();
