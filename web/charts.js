/* Gráficos animados da HUD. Recebem só números e textos curtos, já validados no servidor (viv/tools/charts.py),
   e desenham em SVG: medidores (anéis), barras, linhas e pizza. Tudo entra por textContent/atributos.
   `update` troca os valores de um gráfico já na tela sem refazê-lo, para o painel ao vivo não piscar. */
(function () {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const COLORS = ['var(--viv-rose)', 'var(--viv-cyan)', 'var(--viv-violet)', '#ffc857', '#6ee7a8', '#ff9f6b'];
  const calm = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches && document.documentElement.dataset.motion !== 'full';
  const svg = (tag, attrs) => { const n = document.createElementNS(NS, tag); Object.keys(attrs || {}).forEach(k => n.setAttribute(k, attrs[k])); return n; };
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const fmt = v => (Math.abs(v) >= 100 || Number.isInteger(v) ? Math.round(v) : Math.round(v * 10) / 10).toLocaleString('pt-BR');

  // número que conta até o valor
  function count(node, to, suffix) {
    const from = +node.dataset.value || 0;
    node.dataset.value = to;
    if (calm() || from === to) { node.textContent = fmt(to) + suffix; return; }
    const start = performance.now();
    (function step(now) {
      const p = Math.min(1, (now - start) / 700), v = from + (to - from) * (1 - Math.pow(1 - p, 3));
      node.textContent = fmt(v) + suffix;
      if (p < 1 && node.isConnected) requestAnimationFrame(step); else node.textContent = fmt(to) + suffix;
    })(start);
  }

  const R = 34, LEN = 2 * Math.PI * R;
  function gauges(chart) {
    const box = el('div', 'gauges');
    chart.items.forEach((item, i) => {
      const cell = el('div', 'gauge'); cell.style.setProperty('--i', i);
      const ring = svg('svg', { viewBox: '0 0 84 84', 'aria-hidden': 'true' });
      ring.append(svg('circle', { class: 'gauge-track', cx: 42, cy: 42, r: R }),
        svg('circle', { class: 'gauge-fill', cx: 42, cy: 42, r: R, 'stroke-dasharray': LEN, 'stroke-dashoffset': LEN, stroke: COLORS[i % COLORS.length] }));
      const number = el('b', 'gauge-value', '0');
      cell.append(ring, number, el('span', 'gauge-label', item.label));
      box.append(cell);
    });
    requestAnimationFrame(() => setGauges(box, chart));
    return box;
  }
  function setGauges(box, chart) {
    [...box.children].forEach((cell, i) => {
      const item = chart.items[i]; if (!item) return;
      const share = Math.max(0, Math.min(1, item.value / (item.max || 100)));
      const fill = cell.querySelector('.gauge-fill');
      fill.style.strokeDashoffset = LEN * (1 - share);
      fill.classList.toggle('hot', share >= .9);
      if (item.text) cell.querySelector('.gauge-value').textContent = item.text;
      else count(cell.querySelector('.gauge-value'), item.value, item.unit || chart.unit || '');
      cell.querySelector('.gauge-label').textContent = item.label;
    });
  }

  function bars(chart) {
    const box = el('div', 'bars');
    const top = Math.max(...chart.items.map(i => Math.abs(i.value))) || 1;
    chart.items.forEach((item, i) => {
      const row = el('div', 'bar-row'); row.style.setProperty('--i', i);
      const track = el('div', 'bar-track'), fill = el('i');
      fill.style.background = COLORS[i % COLORS.length];
      track.append(fill);
      const value = el('b', 'bar-value', '0');
      row.append(el('span', 'bar-label', item.label), track, value);
      box.append(row);
      requestAnimationFrame(() => { fill.style.transform = `scaleX(${Math.max(.01, Math.abs(item.value) / top)})`; count(value, item.value, item.unit || chart.unit || ''); });
    });
    return box;
  }

  function line(chart) {
    const W = 520, H = 170, pad = 12, values = chart.items.map(i => i.value);
    const lo = Math.min(...values), hi = Math.max(...values), span = (hi - lo) || 1;
    const x = i => pad + (W - 2 * pad) * i / (values.length - 1), y = v => H - 26 - (H - 50) * (v - lo) / span;
    const d = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
    const root = svg('svg', { viewBox: `0 0 ${W} ${H}`, class: 'line-chart', role: 'img' });
    root.append(svg('path', { class: 'line-area', d: `${d} L${x(values.length - 1).toFixed(1)} ${H - 22} L${x(0).toFixed(1)} ${H - 22} Z` }),
      svg('path', { class: 'line-path', d, pathLength: 1 }));
    const unit = chart.unit || '';
    chart.items.forEach((item, i) => {
      const edge = i === 0 || i === values.length - 1 || item.value === hi || item.value === lo;
      const dot = svg('circle', { class: 'line-dot', cx: x(i).toFixed(1), cy: y(item.value).toFixed(1), r: edge ? 4 : 2.5 });
      dot.style.setProperty('--i', i);
      root.append(dot);
      if (edge) { const t = svg('text', { class: 'line-val', x: x(i).toFixed(1), y: (y(item.value) - 9).toFixed(1) }); t.textContent = fmt(item.value) + unit; root.append(t); }
      if (i === 0 || i === values.length - 1 || values.length <= 8) { const t = svg('text', { class: 'line-cat', x: x(i).toFixed(1), y: H - 6 }); t.textContent = item.label; root.append(t); }
    });
    const box = el('div', 'line-box'); box.append(root);
    return box;
  }

  function pie(chart) {
    const box = el('div', 'pie'), total = chart.items.reduce((s, i) => s + i.value, 0) || 1, r = 40, len = 2 * Math.PI * r;
    const root = svg('svg', { viewBox: '0 0 120 120', 'aria-hidden': 'true' }), group = svg('g', { transform: 'rotate(-90 60 60)' });
    const legend = el('ul', 'pie-legend');
    let start = 0;
    chart.items.forEach((item, i) => {
      const part = len * item.value / total;
      const slice = svg('circle', { class: 'pie-slice', cx: 60, cy: 60, r, stroke: COLORS[i % COLORS.length], 'stroke-dasharray': `${part.toFixed(2)} ${(len - part).toFixed(2)}`, 'stroke-dashoffset': (-start).toFixed(2) });
      slice.style.setProperty('--i', i);
      group.append(slice);
      start += part;
      const row = el('li'); row.style.setProperty('--i', i);
      const key = el('i'); key.style.background = COLORS[i % COLORS.length];
      row.append(key, el('span', null, item.label), el('b', null, `${fmt(100 * item.value / total)}%`));
      legend.append(row);
    });
    root.append(group);
    box.append(root, legend);
    return box;
  }

  function build(chart) {
    const make = { medidores: gauges, barras: bars, linhas: line, pizza: pie }[chart && chart.type];
    if (!make || !Array.isArray(chart.items) || !chart.items.length) return null;
    const node = make(chart);
    node.classList.add('chart');
    node.dataset.type = chart.type;
    return node;
  }

  // Atualiza no lugar quando dá (medidores); senão devolve um nó novo para trocar.
  function update(node, chart) {
    if (node && chart && node.dataset.type === 'medidores' && chart.type === 'medidores' && node.children.length === chart.items.length) {
      setGauges(node, chart);
      return node;
    }
    return build(chart);
  }

  window.VivCharts = { build, update };
})();
