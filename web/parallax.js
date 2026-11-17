/* Profundidade da HUD: as camadas se deslocam um pouco, em ritmos diferentes.
   - --px e --py (de -1 a 1) seguem o mouse e param quando ele para: movem os cartões e o avatar, que precisam
     ficar quietos para serem lidos e clicados.
   - --dx e --dy somam a isso uma deriva lenta e contínua: movem só o fundo e o núcleo, para a tela nunca
     parecer congelada.
   Quem usa as variáveis é o viv.css. Com “reduzir movimento”, todas ficam em zero. */
(function () {
  'use strict';
  const root = document.documentElement;
  const calm = { get matches() { return window.matchMedia('(prefers-reduced-motion: reduce)').matches && document.documentElement.dataset.motion !== 'full'; } };
  let tx = 0, ty = 0, x = 0, y = 0;
  const sent = {};

  window.addEventListener('pointermove', event => {
    tx = event.clientX / window.innerWidth * 2 - 1;
    ty = event.clientY / window.innerHeight * 2 - 1;
  }, { passive: true });

  function set(name, value) {
    const text = value.toFixed(3);
    if (sent[name] === text) return;
    sent[name] = text;
    root.style.setProperty(name, text);
  }

  function frame(now) {
    if (calm.matches || document.hidden) {
      ['--px', '--py', '--dx', '--dy'].forEach(name => set(name, 0));
      setTimeout(() => requestAnimationFrame(frame), 600);
      return;
    }
    x += (tx - x) * 0.07;
    y += (ty - y) * 0.07;
    if (Math.abs(tx - x) < 0.002) x = tx;              // chega ao destino e para de vez
    if (Math.abs(ty - y) < 0.002) y = ty;
    set('--px', x); set('--py', y);
    set('--dx', x + Math.sin(now / 5200) * 0.35); set('--dy', y + Math.cos(now / 6700) * 0.25);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
