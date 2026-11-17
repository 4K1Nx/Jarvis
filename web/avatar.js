/* Avatar da Viv: dois olhos de robô numa telinha de LED azul, no canto da tela (e na miniatura).
   A tela é uma matriz de 20×14 pontos. Os olhos são retângulos arredondados grandes, sem boca, no estilo dos olhos
   animados de robô: cada ponto acende na proporção em que a forma o cobre, então o olhar desliza suave pela matriz.
   Tudo vem de poucos parâmetros levados por molas:
   - para onde ela olha (o mouse, quando ele se mexe; senão olhadas soltas pela tela), e o olho do lado para onde
     ela olha cresce um pouco, de curiosidade;
   - pálpebras: de cima, retas (cansada) ou inclinadas (brava: cantos de dentro descem; triste: os de fora);
     de baixo, em curva (feliz: o olho vira um sorriso “^”);
   - abertura (piscar, dormir), tamanho (susto, atenção), pulinhos (risada) e balanço (confusão, erro).
   Falando, os olhos pulsam com o volume real da voz dela. Com música tocando (Spotify) e ela quieta, os olhos
   sobem felizes, pulam no grave e um equalizador de LED aparece embaixo, com o grave no meio.
   Parada com a aba escondida; com “reduzir movimento”, sem olhadas soltas nem balanços. */
(function () {
  'use strict';
  const box = document.getElementById('avatar');
  const canvas = document.getElementById('avatar-canvas');
  if (!box || !canvas) return;
  const ctx = canvas.getContext('2d');
  const W = 20, H = 14, CELL = +box.dataset.cell || 3;                      // pontos da matriz e tamanho de cada um (px)
  const COLOR = '#4fb8ff';                                                   // LED azul, sempre
  const still = { get matches() { return window.matchMedia('(prefers-reduced-motion: reduce)').matches && document.documentElement.dataset.motion !== 'full'; } };          // reduzido só sem “Animações completas”
  const LABELS = { sleeping: 'dormindo', listening: 'ouvindo', thinking: 'pensando', speaking: 'falando',
                   executing: 'lendo', error: 'com um problema' };
  const REACTIONS = { done: 1600, oops: 2600, surprise: 1400, curious: 2400, cheer: 2200, love: 2400, sleepy: 2000 };

  let state = 'sleeping', mood = 'serena', moodLabel = 'Serena';
  let hibernating = false, asking = false, busy = false;
  let reaction = '', reactionUntil = 0, reactionAt = 0;
  let now = 0, raf = null;
  // voz: nível bruto que chega, envelope suavizado e pico recente (para o ganho se ajustar ao volume dela)
  let raw = 0, heardAt = -1e9, env = 0, peak = 0.25, mic = 0, micEnv = 0;
  // música: bandas do grave ao agudo (0 a 1), suavizadas aqui; somem sozinhas se os eventos pararem
  let bands = [], shown = [], bass = 0, bassEnv = 0, musicAt = -1e9;
  // olhar: alvo vindo do mouse (até 2,5 s depois do último movimento) ou das olhadas soltas
  let pointer = null, pointerAt = -1e9, idle = { x: 0, y: 0 }, nextIdle = 800, blinkAt = 2200, blinkStart = -1e9;

  // humor: pálpebra de cima (0 a 1), inclinação (+ brava, − cansada/triste), sorriso (pálpebra de baixo, 0 a 1)
  const FACES = {
    serena: { lid: 0, slant: 0, happy: 0 }, radiante: { lid: 0, slant: 0, happy: 1 },
    brincalhona: { lid: 0, slant: 0, happy: .6, wink: true }, cansada: { lid: .45, slant: -.35, happy: 0 },
    melancolica: { lid: .2, slant: -.55, happy: 0 }, impaciente: { lid: .35, slant: .15, happy: 0 },
    irritada: { lid: .15, slant: .7, happy: 0 }, magoada: { lid: .2, slant: -.6, happy: 0, away: true },
    frustrada: { lid: .1, slant: .55, happy: 0 }, entediada: { lid: .5, slant: 0, happy: 0, away: true },
  };

  // ---- molas ------------------------------------------------------------------------------------------
  const SPRINGS = {   // rigidez e amortecimento: o olhar é rápido e firme; a forma, mais macia
    gx: [300, .78], gy: [300, .78], size: [220, .6], open: [520, .85], lid: [190, .85], slant: [170, .85],
    happy: [170, .85], wink: [200, .85], hop: [700, .35], shake: [900, .25],
    spin: [110, 1], line: [140, .95], glyph: [160, 1],          // modos: girando, linha, símbolo (0 a 1)
  };
  const eye = { gx: 0, gy: 0, size: 1, open: 0.15, lid: 0, slant: 0, happy: 0, wink: 0, hop: 0, shake: 0,
                spin: 0, line: 0, glyph: 0 };
  let symbol = '';                                                          // “?” ou “!”, enquanto aparece ou some
  const vel = {};
  for (const key in SPRINGS) vel[key] = 0;

  function spring(key, target, dt) {
    const [k, zeta] = SPRINGS[key], c = 2 * Math.sqrt(k) * zeta;
    for (let left = dt; left > 0; left -= 1 / 120) {                        // passos curtos: estável a 30 ou 144 fps
      const step = Math.min(left, 1 / 120);
      vel[key] += (k * (target - eye[key]) - c * vel[key]) * step;
      eye[key] += vel[key] * step;
    }
  }
  const kick = (key, speed) => { if (!still.matches) vel[key] += speed; };   // empurrão: pulinho, balanço

  // ---- para onde olhar --------------------------------------------------------------------------------
  function lookTarget(base) {
    if (pointer && now - pointerAt < 2500) return pointer;
    if (still.matches) return base;
    if (now >= nextIdle) {                                                  // olhadas soltas, como quem observa
      const wander = Math.random() < .6;
      idle = wander ? { x: (Math.random() * 2 - 1) * .9, y: (Math.random() * 2 - 1) * .7 } : { x: 0, y: 0 };
      nextIdle = now + 1200 + Math.random() * 2600;
      if (wander && Math.random() < .25) blinkAt = now + 80;
    }
    return { x: base.x + idle.x, y: base.y + idle.y };
  }

  // Alvo da forma dos olhos para este quadro.
  function eyeTarget(active, mine) {
    const t = { gx: 0, gy: 0, size: 1, open: 1, lid: mine.lid, slant: mine.slant, happy: mine.happy,
                wink: mine.wink ? 1 : 0, hop: 0, shake: 0 };
    let base = { x: mine.away && state !== 'speaking' && state !== 'listening' ? -.8 : 0, y: 0 };
    if (state === 'sleeping') { t.open = .12; t.lid = 0; t.slant = 0; t.happy = 0; t.wink = 0; base = { x: 0, y: .5 }; }
    else if (state === 'error') { t.slant = -.5; t.lid = .2; t.happy = 0; }
    else if (active === 'oops') { t.slant = -.6; t.lid = .15; t.happy = 0; base = { x: 0, y: .5 }; }
    else if (active === 'done' || active === 'cheer' || active === 'love') { t.happy = 1; t.lid = 0; t.slant = 0; }
    else if (active === 'surprise') { t.size = 1.18; t.lid = 0; t.slant = 0; t.happy = 0; }
    else if (active === 'sleepy') { t.lid = .6; t.slant = -.3; t.happy = 0; }
    else if (state === 'thinking') { t.lid = .2; t.happy = 0; base = { x: .8 + Math.sin(now / 1400) * .25, y: -.8 }; }
    else if (state === 'executing') { t.happy = 0; t.lid = Math.max(t.lid, .15); base = { x: Math.sin(now / 480) * 1.1, y: .3 }; }
    else if (active === 'curious' || asking) { t.happy = 0; t.lid = 0; t.slant = -.15; base = { x: .7, y: -.4 }; }
    else if (state === 'listening' && micEnv > .25) { t.size = 1.08; t.lid = 0; }
    if (state === 'speaking') { t.size = 1 + env * .14; base.y -= env * .25; }   // falando: pulsam com a voz
    const look = state === 'thinking' || state === 'executing' || state === 'sleeping' ? base : lookTarget(base);
    t.gx = Math.max(-1.2, Math.min(1.2, look.x)); t.gy = Math.max(-1, Math.min(1, look.y));
    return t;
  }

  // ---- forma de um olho (distância em pontos; negativa dentro). side: -1 esquerdo, +1 direito ----------
  const BASE = { hw: 2.5, hh: 3.1, r: 1.3, gap: 3.9, cy: 6.5 };
  let layout = { cy: BASE.cy, scale: 1 };                                     // com música, os olhos sobem e encolhem
  function eyeDistance(px, py, side) {
    const curious = 1 + Math.max(0, eye.gx * side) * .16;                     // o olho do lado do olhar cresce
    const blink = Math.max(.06, 1 - blinkAmount());
    const hw = BASE.hw * eye.size * layout.scale * (1 + (curious - 1) * .4);
    const hh = BASE.hh * eye.size * layout.scale * curious * Math.max(.06, eye.open) * blink;
    const cx = 9.5 + side * BASE.gap + eye.gx * 2.2 + eye.shake;
    const cy = layout.cy + eye.gy * 2.1 + eye.hop + (1 - Math.min(1, eye.open)) * 1.5;
    const r = Math.min(BASE.r * layout.scale, hw, hh);
    const qx = Math.abs(px - cx) - (hw - r), qy = Math.abs(py - cy) - (hh - r);
    let d = Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - r;
    // pálpebra de cima: reta (cansada) ou inclinada; a de dentro desce (brava) ou a de fora (triste)
    const inward = (side < 0 ? px - cx : cx - px) / hw;
    const lid = cy - hh + eye.lid * 2 * hh + eye.slant * inward * hh * .75 + Math.abs(eye.slant) * hh * .2;
    d = Math.max(d, lid - py);
    // pálpebra de baixo em curva: o olho vira um sorriso; na piscadela só o direito
    const happy = Math.min(1, eye.happy * (side > 0 ? 1 - Math.min(1, eye.wink) : 1));
    if (happy > .01) {
      const ey = cy + hh * (2.4 - happy * 1.3), rx = hw * 2.8, ry = hh * 1.25;   // curva larga: sem “perninhas” nos cantos
      const k = Math.hypot((px - cx) / rx, (py - ey) / ry);
      d = Math.max(d, (1 - k) * Math.min(rx, ry));
    }
    // piscadela: o olho direito fecha num “<”
    if (side > 0 && eye.wink > .01) {
      const tip = [cx - 1.3, cy], top = [cx + 1.5, cy - 1.8], low = [cx + 1.5, cy + 1.8];
      const chevron = Math.min(segment(px, py, tip, top), segment(px, py, tip, low)) - .5;
      d += (chevron - d) * Math.min(1, eye.wink);
    }
    return d;
  }

  function segment(px, py, a, b) {
    const vx = b[0] - a[0], vy = b[1] - a[1];
    const k = Math.max(0, Math.min(1, ((px - a[0]) * vx + (py - a[1]) * vy) / (vx * vx + vy * vy)));
    return Math.hypot(px - a[0] - vx * k, py - a[1] - vy * k);
  }

  // Música: olhos simplificados em linha, um arco “◠” de um ponto de espessura.
  function lineDistance(px, py, side) {
    const cx = 9.5 + side * BASE.gap, cy = layout.cy + 1.4 + eye.hop, r = 2.5;
    return Math.max(Math.abs(Math.hypot(px - cx, py - (cy + 1)) - r) - .45, py - (cy + .4));
  }

  // Pensando: cada olho vira um anel de pontos com um arco claro girando, de cauda que apaga.
  function spinner(px, py, side) {
    const cx = 9.5 + side * BASE.gap, cy = BASE.cy, r = 2.6;
    const ring = Math.max(0, Math.min(1, 1.1 - Math.abs(Math.hypot(px - cx, py - cy) - r) * 1.3));
    if (!ring) return 0;
    const turn = still.matches ? 0 : now / 900 * Math.PI * 2;               // uma volta a cada 0,9 s
    const angle = Math.atan2(py - cy, (px - cx) * side);                     // os dois giram para fora, espelhados
    const behind = ((turn - angle) % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2);
    return ring * Math.max(.12, Math.pow(1 - behind / (Math.PI * 1.4), 1.6));
  }

  // “?” e “!” grandes, no meio da telinha
  const GLYPHS = {
    '?': ['.#####.', '##...##', '.....##', '....##.', '...##..', '...##..', '.......', '...##..', '...##..'],
    '!': ['##', '##', '##', '##', '##', '##', '..', '##', '##'],
  };
  const GLYPH_CELLS = {};
  for (const key in GLYPHS) {
    const rows = GLYPHS[key], left = Math.round((W - rows[0].length) / 2), top = Math.round((H - rows.length) / 2);
    GLYPH_CELLS[key] = new Set();
    rows.forEach((row, y) => [...row].forEach((c, x) => { if (c === '#') GLYPH_CELLS[key].add((top + y) * W + left + x); }));
  }

  function blinkAmount() {
    const k = (now - blinkStart) / 180;                                     // fecha em 70 ms, abre em 110
    if (k < 0 || k > 1) return 0;
    return k < .4 ? Math.sin(k / .4 * Math.PI / 2) : Math.cos((k - .4) / .6 * Math.PI / 2);
  }

  function voice(dt) {
    // sem medida de volume há mais de 0,4 s (HUD aberta sem o áudio), os olhos pulsam no ritmo da fala
    const silent = now - heardAt > 400;
    const target = silent ? (state === 'speaking' ? 0.5 + 0.5 * Math.sin(now / 90) : 0) : raw;
    peak = Math.max(target, peak * Math.pow(0.5, dt / 4000), 0.12);          // o pico cai pela metade a cada 4 s
    const level = Math.min(1, target / peak);
    env += (level - env) * Math.min(1, dt / (level > env ? 35 : 110));       // sobe rápido, desce mais devagar
    micEnv += (mic - micEnv) * Math.min(1, dt / 120);
    const on = now - musicAt < 700;
    for (let i = 0; i < 10; i++) {
      const goal = on ? bands[i] || 0 : 0, cur = shown[i] || 0;
      shown[i] = cur + (goal - cur) * Math.min(1, dt / (goal > cur ? 40 : 140));
    }
    bassEnv += ((on ? bass : 0) - bassEnv) * Math.min(1, dt / (bass > bassEnv ? 30 : 160));
  }

  function dancing() {
    return now - musicAt < 700 && !hibernating && (state === 'sleeping' || state === 'listening' && micEnv < 0.25);
  }

  // Equalizador embaixo dos olhos: linhas 10 a 13, grave no centro, agudo nas pontas.
  function equalizer(cells) {
    for (let x = 0; x < W; x++) {
      const band = x < W / 2 ? W / 2 - 1 - x : x - W / 2;
      const height = Math.round(Math.min(1, shown[band] || 0) * 4);
      for (let k = 0; k < height; k++) cells.push([x, 13 - k]);
    }
  }

  // Um quadro: atualiza as molas e devolve os pontos fixos (enfeites) acesos.
  function step(dt) {
    const t = now, slow = Math.floor(t / 375), mine = FACES[mood] || FACES.serena;
    const active = t < reactionUntil ? reaction : '';
    const cells = [];
    const music = dancing() && !active;
    const goal = music ? { cy: 4.4, scale: .8 } : { cy: BASE.cy, scale: 1 };
    layout.cy += (goal.cy - layout.cy) * Math.min(1, dt * 8);
    layout.scale += (goal.scale - layout.scale) * Math.min(1, dt * 8);
    const target = music
      ? { gx: 0, gy: 0, size: 1, open: 1, lid: 0, slant: 0, happy: 1, wink: 0, hop: 0, shake: 0 }
      : eyeTarget(active, mine);
    // modos inteiros do rosto: pensando gira, música vira linha, pergunta e erro viram símbolo
    const wanted = state === 'error' ? '!' : asking && !active ? '?' : '';
    if (wanted) symbol = wanted;
    target.glyph = wanted ? 1 : 0;
    target.spin = !wanted && !active && (state === 'thinking' || state === 'executing') ? 1 : 0;
    target.line = music ? 1 : 0;
    for (const key in SPRINGS) spring(key, target[key], dt);
    if (eye.glyph < .02 && !wanted) symbol = '';
    if (music && bassEnv > .55 && eye.hop > -.2) kick('hop', -14 * bassEnv);  // pulinho no grave
    // reações com movimento: risada pula, confusão e erro balançam (empurrões na mola, que volta sozinha)
    if (active && t - reactionAt < 40) {
      if (active === 'cheer' || active === 'love') kick('hop', -30);
      if (active === 'oops') kick('shake', 40);
      if (active === 'surprise') kick('size', 2.5);
    }
    if ((active === 'cheer' || active === 'love') && Math.floor((t - reactionAt) / 260) % 2 === 0 && eye.hop > -.1) kick('hop', -9);
    if (state === 'error' && t % 1400 < 30) kick('shake', 30);
    if (state !== 'sleeping' && !hibernating && !still.matches && now >= blinkAt) {
      blinkStart = now; blinkAt = now + 2200 + Math.random() * 3600;
    }
    if (music) equalizer(cells);
    if (state === 'sleeping' && !still.matches && !music) {   // um “z” pequeno que sobe no canto
      const y = 3 - Math.floor(t / 625) % 3;
      cells.push([16, y], [17, y], [17, y + 1], [16, y + 2], [17, y + 2]);
    }
    if ((mine.slant < -.5 || mood === 'melancolica') && !active && state !== 'sleeping' && !still.matches) {
      const drop = Math.floor(t / 240) % 16;            // lágrima que escorre de vez em quando
      if (drop < 4) cells.push([3, 10 + drop]);
    }
    if (busy && state !== 'sleeping' && !still.matches) {   // tarefa em segundo plano: três pontos correndo no rodapé
      const head = Math.floor(t / 160) % 6;
      for (let i = 0; i < 3; i++) cells.push([1 + ((head + i) % 6), 13]);
    }
    return cells;
  }

  const light = new Float32Array(W * H);
  let last = 0;
  function draw(time) {
    raf = null;
    if (box.hidden || document.hidden) return;
    const dt = Math.min(100, time - last || 16);
    last = now = time;
    voice(dt);
    light.fill(0);
    if (hibernating) {                                // tela apagada, com um ponto que respira
      for (const [x, y] of Math.sin(now / 900) > -0.2 ? [[9, 6], [10, 6], [9, 7], [10, 7]] : [[9, 7], [10, 7]]) light[y * W + x] = 1;
    } else {
      const cells = step(dt / 1000);
      for (let y = 0; y < H; y++) {
        for (let x = 0; x < W; x++) {
          let d = Math.min(eyeDistance(x, y, -1), eyeDistance(x, y, 1));
          if (eye.line > .01) d += (Math.min(lineDistance(x, y, -1), lineDistance(x, y, 1)) - d) * Math.min(1, eye.line);
          let on = Math.max(0, Math.min(1, .55 - d));                  // borda macia: meio ponto aceso pela metade
          if (eye.spin > .01) on += (Math.max(spinner(x, y, -1), spinner(x, y, 1)) - on) * Math.min(1, eye.spin);
          if (eye.glyph > .01) on += ((GLYPH_CELLS[symbol] && GLYPH_CELLS[symbol].has(y * W + x) ? 1 : 0) - on) * Math.min(1, eye.glyph);
          light[y * W + x] = on;
        }
      }
      for (const [x, y] of cells) if (x >= 0 && x < W && y >= 0 && y < H) light[y * W + x] = 1;
    }
    // a matriz é desenhada no tamanho em que aparece na tela, para os pontos ficarem nítidos em qualquer tamanho
    const scale = (window.devicePixelRatio || 1) * Math.max(1, (canvas.clientWidth || W * CELL) / (W * CELL));
    if (canvas.width !== Math.round(W * CELL * scale)) { canvas.width = Math.round(W * CELL * scale); canvas.height = Math.round(H * CELL * scale); }
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    ctx.clearRect(0, 0, W * CELL, H * CELL);
    const dim = hibernating ? 0.35 : state === 'sleeping' && !dancing() ? 0.6 : 1;
    ctx.fillStyle = 'rgba(120, 190, 255, 0.06)';
    ctx.globalAlpha = hibernating ? .4 : 1;
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {             // a grade apagada
      if (light[y * W + x] > .04) continue;
      ctx.beginPath(); ctx.arc(x * CELL + CELL / 2, y * CELL + CELL / 2, CELL * .3, 0, Math.PI * 2); ctx.fill();
    }
    ctx.fillStyle = COLOR; ctx.shadowColor = COLOR;
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const on = light[y * W + x];
      if (on <= .04) continue;
      ctx.globalAlpha = dim * (.2 + .8 * on);
      ctx.shadowBlur = CELL * 1.3 * on;
      ctx.beginPath(); ctx.arc(x * CELL + CELL / 2, y * CELL + CELL / 2, CELL * (.3 + .12 * on), 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = 1; ctx.shadowBlur = 0;
    raf = requestAnimationFrame(draw);
  }

  function describe() {
    const doing = hibernating ? 'hibernando' : asking ? 'esperando a sua resposta' : LABELS[state] || state;
    const text = `Viv: ${doing}${moodLabel && !hibernating ? ', ' + moodLabel.toLowerCase() : ''}${busy ? ', com tarefa em andamento' : ''}`;
    box.title = text;
    box.setAttribute('aria-label', text);
  }

  function run() {
    if (raf) cancelAnimationFrame(raf);
    raf = null;
    if (box.hidden || document.hidden) return;
    last = 0;
    raf = requestAnimationFrame(draw);
  }
  document.addEventListener('visibilitychange', run);

  function react(name) {
    if (!REACTIONS[name] || hibernating) return;
    reaction = name; reactionAt = performance.now(); reactionUntil = reactionAt + REACTIONS[name];
  }

  /* Olhar para um ponto: dx, dy de −1 a 1 (direita e baixo positivos), ou null para soltar. */
  function lookAt(dx, dy) {
    if (dx == null || dy == null) { pointer = null; return; }
    pointer = { x: Math.max(-1.2, Math.min(1.2, +dx || 0)), y: Math.max(-1, Math.min(1, +dy || 0)) };
    pointerAt = performance.now();
  }
  // o mouse dentro da página: a distância até a telinha vira a direção do olhar (a uns 600 px ela olha no limite)
  document.addEventListener('pointermove', event => {
    const rect = box.getBoundingClientRect();
    if (!rect.width) return;
    const dx = (event.clientX - (rect.left + rect.width / 2)) / 600, dy = (event.clientY - (rect.top + rect.height / 2)) / 450;
    const far = Math.max(1, Math.hypot(dx, dy));
    lookAt(dx / far * 1.2, dy / far);
  }, { passive: true });

  window.VivAvatar = {
    setState(next) {
      if (next !== state) {
        if (state === 'sleeping' && next !== 'sleeping' && next !== 'error') react('surprise');   // acordou
        if (next === 'sleeping' && state !== 'sleeping') react('sleepy');
        nextIdle = 0;
      }
      state = next; box.dataset.state = next; describe();
    },
    setMood(data) {
      if (!data) return;
      const before = mood;
      if (data.name) mood = data.name;
      if (data.label || data.text) moodLabel = data.label || data.text;
      if (data.enabled === false) { mood = 'serena'; moodLabel = ''; }
      if (mood !== before && mood === 'radiante') react('love');
      if (mood !== before && ['magoada', 'frustrada', 'irritada'].includes(mood)) react('oops');
      describe();
    },
    setLevel(source, value) {
      const v = Math.max(0, Math.min(1, +value || 0));
      if (source === 'out') { raw = v; heardAt = performance.now(); } else if (source === 'mic') mic = v;
    },
    setMusic(data) {
      if (!data || !data.playing || !Array.isArray(data.bands)) { musicAt = -1e9; return; }
      bands = data.bands.slice(0, 10).map(v => Math.max(0, Math.min(1, +v || 0)));
      bass = Math.max(0, Math.min(1, +data.bass || 0));
      musicAt = performance.now();
      if (!raf) run();
    },
    setLook(look) {                                      // tamanho e opacidade escolhidos nas configurações (%)
      if (!look) return;
      const size = Math.max(50, Math.min(300, +look.size || 100)), alpha = Math.max(20, Math.min(100, +look.opacity || 100));
      box.style.setProperty('--avatar-scale', size / 100);
      box.style.setProperty('--avatar-alpha', alpha / 100);
    },
    lookAt,
    react,
    setAsking(on) { asking = !!on; describe(); },
    setBusy(on) { busy = !!on; describe(); },
    setHibernating(on) { hibernating = !!on; box.dataset.hibernating = hibernating ? 'true' : 'false'; describe(); },
    show(visible) { box.hidden = !visible; run(); },
  };
  describe();
  run();
})();
