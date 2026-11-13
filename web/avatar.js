/* Avatar da Viv: um rostinho de robô numa telinha de LED, no canto da tela.
   A tela é uma matriz de 20×14 pontos; acendem só os que formam os olhos, as sobrancelhas e a
   boca, na cor do humor. O estado muda o rosto (dormindo, ouvindo, pensando, falando, lendo,
   erro) e o humor muda a expressão (sorriso, piscadela, olhar cansado, sobrancelhas franzidas).
   A boca acompanha o volume da voz dela. Anima a 8 quadros por segundo, parada com a aba
   escondida; com “reduzir movimento”, só pisca e fala. */
(function () {
  'use strict';
  const box = document.getElementById('avatar');
  const canvas = document.getElementById('avatar-canvas');
  if (!box || !canvas) return;
  const ctx = canvas.getContext('2d');
  const W = 20, H = 14, CELL = 3;                      // pontos da matriz e tamanho de cada um (px)
  const still = window.matchMedia('(prefers-reduced-motion: reduce)');
  const LABELS = { sleeping: 'dormindo', listening: 'ouvindo', thinking: 'pensando', speaking: 'falando',
                   executing: 'lendo', error: 'com um problema' };

  let state = 'sleeping', mood = 'serena', moodLabel = 'Serena', color = '#5fe6ff';
  let frame = 0, level = 0, blinkAt = 30, timer = null;

  // ---- peças do rosto, em coordenadas da matriz (olho esquerdo; o direito é o espelho) ----------
  const mirror = cells => cells.map(([x, y]) => [W - 1 - x, y]);
  const EYE_X = 5.5, EYE_Y = 5.5;

  function eyeOval(look, lid) {
    const cells = [];
    for (let y = 2; y <= 9; y++) {
      for (let x = 2; x <= 9; x++) {
        if (((x - EYE_X) / 2.4) ** 2 + ((y - EYE_Y) / 2.9) ** 2 > 1) continue;
        if ((x - EYE_X - look) ** 2 + (y - EYE_Y) ** 2 <= 0.8) continue;   // pupila: os pontos apagados
        if (y < lid) continue;                                            // pálpebra caída
        cells.push([x, y]);
      }
    }
    return cells;
  }
  const EYES = {
    happy: [[3, 6], [4, 5], [5, 4], [6, 4], [7, 5], [8, 6]],            // ^
    closed: [[3, 5], [4, 6], [5, 6], [6, 6], [7, 6], [8, 5]],           // ‿
    line: [[4, 6], [5, 6], [6, 6], [7, 6]],
    x: [[4, 4], [7, 4], [5, 5], [6, 5], [5, 6], [6, 6], [4, 7], [7, 7]],
  };
  const BROWS = {
    angry: [[4, 1], [5, 1], [6, 2], [7, 2]],
    sad: [[4, 2], [5, 2], [6, 1], [7, 1]],
    flat: [[4, 1], [5, 1], [6, 1], [7, 1]],
  };
  const row = (from, to, y) => Array.from({ length: to - from + 1 }, (_, i) => [from + i, y]);
  const MOUTHS = {
    smile: [[7, 10], ...row(8, 11, 11), [12, 10]],
    grin: [[6, 10], ...row(7, 12, 11), [13, 10], ...row(8, 11, 12)],
    small: row(9, 10, 11),
    flat: row(7, 12, 11),
    frown: [[7, 12], ...row(8, 11, 11), [12, 12]],
    wavy: [[6, 11], [7, 10], [8, 11], [9, 12], [10, 12], [11, 11], [12, 10], [13, 11]],
  };
  const FACES = {
    serena: { mouth: 'smile', lid: 4 }, radiante: { mouth: 'grin', eyes: 'happy' },
    brincalhona: { mouth: 'grin', wink: true }, cansada: { mouth: 'small', lid: 6 },
    melancolica: { mouth: 'frown', brows: 'sad', lid: 4 }, impaciente: { mouth: 'flat', brows: 'flat', lid: 5, raised: true },
    irritada: { mouth: 'frown', brows: 'angry', lid: 5 },
  };

  function talking() {
    // boca aberta conforme o volume da voz; sem medida de volume, abre e fecha no ritmo
    const open = level ? (level > 0.45 ? 2 : level > 0.12 ? 1 : 0) : [0, 1, 2, 1][frame % 4];
    const cells = row(8, 11, 11);
    for (let h = 1; h <= open; h++) cells.push(...row(8, 11, 11 - h), ...row(8, 11, 11 + h));
    return open ? cells.concat([[7, 11], [12, 11]]) : cells;
  }

  // Pontos acesos neste quadro.
  function face() {
    const look = { executing: [-1, 0, 1, 0][Math.floor(frame / 3) % 4], thinking: frame % 16 < 8 ? 1 : 0 }[state] || 0;
    const mine = FACES[mood] || FACES.serena;
    const blinking = state !== 'sleeping' && state !== 'error' && frame >= blinkAt && frame < blinkAt + 2;
    let left, right, mouth, brows = mine.brows;

    if (state === 'sleeping') { left = right = EYES.closed; mouth = MOUTHS.small; brows = null; }
    else if (state === 'error') { left = right = EYES.x; mouth = MOUTHS.wavy; brows = 'sad'; }
    else {
      const lid = state === 'thinking' ? 3 : mine.lid || 0;
      // o olho direito é desenhado como o esquerdo e espelhado: o olhar dele vai para o lado contrário
      left = blinking ? EYES.line : mine.eyes === 'happy' ? EYES.happy : eyeOval(look, lid);
      right = blinking ? EYES.line : mine.eyes === 'happy' ? EYES.happy : eyeOval(-look, lid);
      if (mine.wink && !blinking) right = EYES.happy;
      mouth = state === 'speaking' ? talking() : state === 'thinking' ? [] : state === 'executing' ? MOUTHS.flat
        : MOUTHS[mine.mouth];
    }
    const cells = [...left, ...mirror(right), ...mouth];
    if (brows) {
      const pair = BROWS[brows];
      cells.push(...pair, ...mirror(mine.raised ? pair.map(([x, y]) => [x, y - 1]) : pair));
    }
    if (state === 'thinking') {                       // três pontinhos que acendem um depois do outro
      const lit = Math.floor(frame / 3) % 4;
      [[6, 7], [9, 10], [12, 13]].slice(0, lit).forEach(([a, b]) => cells.push([a, 11], [b, 11]));
    }
    if (state === 'sleeping' && !still.matches) {     // um “z” pequeno que sobe no canto
      const y = 3 - Math.floor(frame / 5) % 3;
      cells.push([16, y], [17, y], [17, y + 1], [16, y + 2], [17, y + 2]);
    }
    return cells;
  }

  function draw() {
    const scale = window.devicePixelRatio || 1;
    if (canvas.width !== W * CELL * scale) { canvas.width = W * CELL * scale; canvas.height = H * CELL * scale; }
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    ctx.clearRect(0, 0, W * CELL, H * CELL);
    const lit = new Set(face().filter(([x, y]) => x >= 0 && x < W && y >= 0 && y < H).map(([x, y]) => y * W + x));
    const dim = state === 'sleeping' ? 0.55 : 1;
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const on = lit.has(y * W + x);
        ctx.globalAlpha = on ? dim : 1;
        ctx.fillStyle = on ? color : 'rgba(255, 255, 255, 0.05)';
        ctx.shadowColor = color; ctx.shadowBlur = on ? 4 : 0;
        ctx.beginPath();
        ctx.arc(x * CELL + CELL / 2, y * CELL + CELL / 2, on ? 1.25 : 0.9, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.globalAlpha = 1; ctx.shadowBlur = 0;
    frame += 1;
    if (frame > blinkAt + 2) blinkAt = frame + 24 + Math.floor(Math.random() * 30);
    if (frame > 960) { frame = 0; blinkAt = 30; }
  }

  function describe() {
    const text = `Viv: ${LABELS[state] || state}${moodLabel ? ', ' + moodLabel.toLowerCase() : ''}`;
    box.title = text;
    box.setAttribute('aria-label', text);
  }

  function run() {
    clearInterval(timer); timer = null;
    if (box.hidden || document.hidden) return;
    draw();
    timer = setInterval(draw, 125);
  }
  document.addEventListener('visibilitychange', run);

  window.VivAvatar = {
    setState(next) { state = next; box.dataset.state = next; describe(); },
    setMood(data) {
      if (!data) return;
      if (data.name) mood = data.name;
      if (data.label || data.text) moodLabel = data.label || data.text;
      if (data.enabled === false) { mood = 'serena'; moodLabel = ''; }
      const palette = data.palette;
      if (Array.isArray(palette) && palette.length >= 3 && /^#[0-9a-f]{6}$/i.test(palette[2])) color = palette[2];
      describe();
    },
    setLevel(source, value) { if (source === 'out') level = Math.max(0, Math.min(1, +value || 0)); },
    show(visible) { box.hidden = !visible; run(); },
  };
  describe();
  run();
})();
