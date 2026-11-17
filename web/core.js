/* Núcleo animado da Viv: orbe em canvas que reage ao estado e ao nível real de áudio. */
(function () {
  'use strict';
  const canvas = document.getElementById('core');
  const ctx = canvas.getContext('2d');
  const css = getComputedStyle(document.documentElement);
  const hex = name => css.getPropertyValue(name).trim();
  const rgb = h => { const n = parseInt(h.slice(1), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; };
  const COLORS = { rose: rgb(hex('--viv-rose')), violet: rgb(hex('--viv-violet')), cyan: rgb(hex('--viv-cyan')), danger: rgb(hex('--viv-danger')) };
  const rgba = (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${Math.max(0, Math.min(1, a))})`;
  const calm = () => matchMedia('(prefers-reduced-motion: reduce)').matches && document.documentElement.dataset.motion !== 'full';   // reduzido só sem “Animações completas”

  // glow: brilho geral; speed: giro dos anéis; open: abertura dos anéis; wave: amplitude da onda;
  // pull: quanto as partículas convergem para o centro; a/b: cores principal e secundária.
  const LOOK = {
    sleeping:  { glow: .22, speed: .12, open: .90, wave: .10, pull: 0,   a: 'violet', b: 'violet' },
    listening: { glow: .70, speed: .45, open: 1.12, wave: 1.0, pull: 0,   a: 'cyan',   b: 'violet' },
    thinking:  { glow: .80, speed: 2.4, open: .97, wave: .25, pull: 1,   a: 'violet', b: 'rose' },
    speaking:  { glow: 1.0, speed: .75, open: 1.04, wave: 1.35, pull: 0,  a: 'rose',   b: 'violet' },
    executing: { glow: .85, speed: 1.3, open: 1.0, wave: .30, pull: .35, a: 'cyan',   b: 'rose' },
    error:     { glow: .90, speed: .25, open: .95, wave: .15, pull: 0,   a: 'danger', b: 'danger' },
  };

  let W = 0, H = 0, cx = 0, cy = 0, R = 0;
  let state = 'sleeping', stateAt = performance.now();
  const levels = { mic: 0, out: 0 };
  const cur = { glow: .22, speed: .12, open: .9, wave: .1, pull: 0, a: COLORS.violet.slice(), b: COLORS.violet.slice() };
  let level = 0, spin = 0, last = performance.now();
  const waves = [];          // ondas que saem do núcleo quando o estado muda: {at, color}

  const particles = Array.from({ length: 84 }, (_, i) => ({
    angle: Math.random() * Math.PI * 2, orbit: 1.2 + Math.random() * .95,
    speed: (.12 + Math.random() * .35) * (i % 2 ? 1 : -1), size: .6 + Math.random() * 1.5, phase: Math.random() * 6.28,
  }));
  const RINGS = [
    { r: 1.34, width: 1.2, dir: 1,  k: .6, arcs: [[0, 1.5], [2.0, 1.1], [3.6, 2.1]] },
    { r: 1.20, width: 2.4, dir: -1, k: 1.0, arcs: [[.4, 2.3], [3.3, .7], [4.5, 1.2]] },
    { r: 1.07, width: 1.0, dir: 1,  k: 1.6, arcs: [[1.0, .9], [2.6, 2.6], [5.6, .5]] },
  ];

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cx = W / 2; cy = H * .42; R = Math.max(54, Math.min(W, H) * .165);
    window.dispatchEvent(new CustomEvent('viv-core-moved'));
  }

  const mix = (from, to, k) => from + (to - from) * k;
  // ruído suave e periódico no ângulo, feito de senos
  const ripple = (angle, t) => Math.sin(angle * 3 + t * 2.1) * .5 + Math.sin(angle * 7 - t * 3.3) * .3 + Math.sin(angle * 13 + t * 5.2) * .2;

  function frame(now) {
    const dt = Math.min(.05, (now - last) / 1000); last = now;
    const t = now / 1000, look = LOOK[state] || LOOK.sleeping, ease = 1 - Math.pow(.002, dt);
    for (const key of ['glow', 'speed', 'open', 'wave', 'pull']) cur[key] = mix(cur[key], look[key], ease);
    for (let i = 0; i < 3; i++) { cur.a[i] = mix(cur.a[i], COLORS[look.a][i], ease); cur.b[i] = mix(cur.b[i], COLORS[look.b][i], ease); }
    const target = state === 'speaking' ? levels.out : state === 'listening' ? levels.mic : Math.max(levels.mic, levels.out) * .25;
    level = mix(level, target, target > level ? .35 : .08);
    spin += dt * cur.speed * (calm() ? .2 : 1);
    const breath = Math.sin(t * (state === 'sleeping' ? .9 : 1.7)) * .5 + .5;

    ctx.clearRect(0, 0, W, H);
    ctx.save();
    const sinceChange = now - stateAt;
    if (state === 'error' && sinceChange < 700 && !calm()) {           // tremor amortecido, não aleatório
      const k = sinceChange / 700;
      ctx.translate(Math.sin(sinceChange / 22) * 6 * (1 - k) * (1 - k), 0);
    }

    // halo
    const halo = ctx.createRadialGradient(cx, cy, R * .2, cx, cy, R * 2.9);
    halo.addColorStop(0, rgba(cur.a, .30 * cur.glow + level * .28));
    halo.addColorStop(.45, rgba(cur.b, .10 * cur.glow + level * .08));
    halo.addColorStop(1, rgba(cur.b, 0));
    ctx.fillStyle = halo; ctx.fillRect(0, 0, W, H);

    // régua externa
    const tickR = R * 1.56 * cur.open;
    ctx.lineWidth = 1;
    for (let i = 0; i < 96; i++) {
      const a = i / 96 * Math.PI * 2 + spin * .15, long = i % 8 === 0;
      const r1 = tickR, r2 = tickR + (long ? R * .07 : R * .03);
      ctx.strokeStyle = rgba(long ? cur.a : cur.b, (long ? .55 : .22) * cur.glow);
      ctx.beginPath(); ctx.moveTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1); ctx.lineTo(cx + Math.cos(a) * r2, cy + Math.sin(a) * r2); ctx.stroke();
    }

    // anéis em arcos
    ctx.lineCap = 'round';
    RINGS.forEach((ring, index) => {
      const radius = R * ring.r * cur.open * (1 + level * .05 * (index + 1));
      ctx.lineWidth = ring.width;
      ctx.strokeStyle = rgba(index === 1 ? cur.a : cur.b, (.45 + index * .12) * cur.glow + level * .25);
      ctx.shadowColor = rgba(cur.a, .7 * cur.glow); ctx.shadowBlur = index === 1 ? 14 : 6;
      for (const [start, length] of ring.arcs) {
        const a0 = start + spin * ring.dir * ring.k;
        ctx.beginPath(); ctx.arc(cx, cy, radius, a0, a0 + length); ctx.stroke();
      }
    });

    // arcos de progresso ao executar
    const exec = state === 'executing' ? 1 : 0;
    if (exec) {
      ctx.lineWidth = 3.2; ctx.shadowBlur = 16; ctx.shadowColor = rgba(COLORS.cyan, .9);
      for (let i = 0; i < 2; i++) {
        const a0 = t * 2.6 + i * Math.PI, sweep = 1.0 + Math.sin(t * 3 + i) * .55;
        ctx.strokeStyle = rgba(i ? COLORS.rose : COLORS.cyan, .9);
        ctx.beginPath(); ctx.arc(cx, cy, R * 1.45, a0, a0 + sweep); ctx.stroke();
      }
    }

    // onda circular (duas camadas)
    for (let layer = 0; layer < 2; layer++) {
      const color = layer ? cur.b : cur.a, amp = R * (.035 + .24 * cur.wave * level) * (layer ? .7 : 1);
      ctx.beginPath();
      for (let i = 0; i <= 180; i++) {
        const a = i / 180 * Math.PI * 2;
        const r = R * (.86 + breath * .02) + amp * ripple(a + layer * 1.3, t * (layer ? -.8 : 1));
        const x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r;
        if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
      }
      ctx.closePath();
      ctx.lineWidth = layer ? 1.2 : 2.2; ctx.shadowBlur = layer ? 8 : 20; ctx.shadowColor = rgba(color, .9 * cur.glow);
      ctx.strokeStyle = rgba(color, (layer ? .5 : .9) * (.35 + cur.glow * .65)); ctx.stroke();
    }
    ctx.shadowBlur = 0;

    // coração do núcleo
    const heart = R * (.46 + breath * .035 + level * .16);
    const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, heart);
    core.addColorStop(0, rgba([255, 255, 255], .85 * cur.glow + level * .15));
    core.addColorStop(.28, rgba(cur.a, .75 * cur.glow));
    core.addColorStop(.7, rgba(cur.b, .22 * cur.glow));
    core.addColorStop(1, rgba(cur.b, 0));
    ctx.fillStyle = core; ctx.beginPath(); ctx.arc(cx, cy, heart, 0, Math.PI * 2); ctx.fill();

    // ondas de mudança de estado: um anel fino que se expande e some, com desaceleração
    for (let i = waves.length - 1; i >= 0; i--) {
      const k = (now - waves[i].at) / 1100;
      if (k >= 1) { waves.splice(i, 1); continue; }
      const out = 1 - Math.pow(1 - k, 3);
      ctx.lineWidth = 1.5 * (1 - k) + .5;
      ctx.shadowBlur = 12; ctx.shadowColor = rgba(waves[i].color, .6 * (1 - k));
      ctx.strokeStyle = rgba(waves[i].color, .55 * (1 - k) * (1 - k));
      ctx.beginPath(); ctx.arc(cx, cy, R * (.9 + out * .95), 0, Math.PI * 2); ctx.stroke();
    }
    ctx.shadowBlur = 0;

    // partículas
    for (const p of particles) {
      p.angle += dt * p.speed * (.4 + cur.speed * .6) * (calm() ? .2 : 1);
      const pulse = cur.pull * (.5 + .5 * Math.sin(t * 2.2 + p.phase));
      const orbit = R * mix(p.orbit, .62, pulse * .8) * cur.open;
      const x = cx + Math.cos(p.angle) * orbit, y = cy + Math.sin(p.angle) * orbit * .98;
      ctx.fillStyle = rgba(p.phase > 3.14 ? cur.a : cur.b, (.25 + .5 * Math.abs(Math.sin(t + p.phase))) * cur.glow);
      ctx.beginPath(); ctx.arc(x, y, p.size * (1 + level * .8), 0, Math.PI * 2); ctx.fill();
    }
    ctx.restore();
    requestAnimationFrame(frame);
  }

  window.VivCore = {
    setState(next) {
      if (!LOOK[next] || next === state) return;
      state = next; stateAt = performance.now();
      if (!calm() && next !== 'sleeping') waves.push({ at: stateAt, color: COLORS[LOOK[next].a].slice() });
      if (waves.length > 3) waves.shift();
    },
    setLevel(source, value) { if (source in levels) levels[source] = Math.max(0, Math.min(1, +value || 0)); },
    center() { return { x: cx, y: cy, r: R * 1.6 }; },
    // cores do humor: principal, secundária e destaque; o desenho desliza até elas sozinho
    setPalette(rose, violet, cyan) {
      for (const [name, value] of [['rose', rose], ['violet', violet], ['cyan', cyan]]) {
        if (/^#[0-9a-f]{6}$/i.test(value || '')) COLORS[name] = rgb(value);
      }
    },
  };
  window.addEventListener('resize', resize);
  resize();
  requestAnimationFrame(frame);
})();
