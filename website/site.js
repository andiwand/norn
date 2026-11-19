// The tour: which chapter is in view sets body[data-chapter], the screens of the stage and the
// rail follow it. Also the install tabs and the copy buttons. Without this script the page still
// reads in full: every chapter has its own picture on narrow screens, and the first screen of the
// stage shows on wide ones.
(() => {
  const body = document.body;
  const screens = [...document.querySelectorAll('#stage [data-for]')];
  const rail = [...document.querySelectorAll('#rail a')];
  const chapters = [...document.querySelectorAll('[data-chapter]')].filter((el) => el.matches('section, .rest'));

  function show(name) {
    if (body.dataset.chapter === name) return;
    body.dataset.chapter = name;
    // Each screen names the chapters it belongs to; the first one that fits shows.
    for (const group of [...document.querySelectorAll('#stage .screen'), document.querySelector('#stage .phone')]) {
      const own = [...group.children].filter((el) => el.dataset.for);
      const match = own.find((el) => el.dataset.for.split(' ').includes(name));
      for (const el of own) el.classList.toggle('on', el === (match ?? (el.classList.contains('push') ? null : own[0])) );
    }
    for (const a of rail) {
      if (a.dataset.chapter === name) a.setAttribute('aria-current', 'step');
      else a.removeAttribute('aria-current');
    }
    for (const c of document.querySelectorAll('.chapter')) c.classList.toggle('current', c.dataset.chapter === name);
  }

  // The chapter whose middle band (40 to 60 % of the window) the page has reached.
  const seen = new Map();
  const observer = new IntersectionObserver(
    (entries) => {
      for (const e of entries) seen.set(e.target, e.isIntersecting);
      const current = chapters.filter((c) => seen.get(c)).at(-1);
      if (current) show(current.dataset.chapter);
    },
    { rootMargin: '-40% 0px -55% 0px' }
  );
  for (const c of chapters) observer.observe(c);
  body.dataset.chapter = '';
  show('hero');

  // The hero's ruler: the playhead drifts through the day (slower over a recording) and shows the
  // time where it stands and what was recorded there. The pointer takes it over, a finger too.
  const ruler = document.querySelector('.ruler-track');
  if (ruler) {
    const head = ruler.querySelector('.playhead');
    const label = head.querySelector('em');
    const clips = [...ruler.querySelectorAll('.clip')].map((el) => {
      const left = parseFloat(el.style.left) / 100;
      return { el, from: left - 0.004, to: left + parseFloat(el.style.width) / 100 + 0.004 };
    });
    const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
    let at = 0.88;
    let speed = -0.045; // of the day per second
    let held = false;
    let release = 0;
    let hit = null;

    function place(fraction) {
      at = Math.min(1, Math.max(0, fraction));
      const minutes = Math.min(Math.round(at * 1440), 1439);
      const time = `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
      hit = clips.find((c) => at >= c.from && at <= c.to) ?? null;
      for (const c of clips) c.el.classList.toggle('hit', c === hit);
      head.style.left = `${at * 100}%`;
      head.classList.toggle('flip', at > 0.6);
      label.textContent = hit ? `${time} · ${hit.el.dataset.what}` : time;
    }

    function follow(e) {
      const box = ruler.getBoundingClientRect();
      held = true;
      clearTimeout(release);
      place((e.clientX - box.left) / box.width);
    }
    ruler.addEventListener('pointermove', (e) => {
      if (e.pointerType === 'mouse' || e.buttons) follow(e);
    });
    ruler.addEventListener('pointerdown', follow);
    ruler.addEventListener('pointerleave', () => (held = false));
    ruler.addEventListener('pointerup', (e) => {
      if (e.pointerType !== 'mouse') release = setTimeout(() => (held = false), 2000);
    });

    let last = 0;
    function drift(now) {
      const seconds = Math.min(0.1, (now - last) / 1000 || 0);
      last = now;
      if (!held) {
        let next = at + speed * seconds * (hit ? 0.3 : 1);
        if (next < 0.04 || next > 0.96) {
          speed = -speed;
          next = Math.min(0.96, Math.max(0.04, next));
        }
        place(next);
      }
      requestAnimationFrame(drift);
    }
    place(at);
    if (!still) requestAnimationFrame(drift);
  }

  // Install: Docker or Python.
  const tabs = [...document.querySelectorAll('.tabs [role="tab"]')];
  function pick(tab) {
    for (const t of tabs) {
      const on = t === tab;
      t.setAttribute('aria-selected', String(on));
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute('aria-controls')).hidden = !on;
    }
  }
  for (const t of tabs) {
    t.addEventListener('click', () => pick(t));
    t.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      const next = tabs[(tabs.indexOf(t) + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
      pick(next);
      next.focus();
    });
  }

  // Copy buttons: the code next to them.
  for (const button of document.querySelectorAll('.copy')) {
    button.addEventListener('click', async () => {
      const text = button.parentElement.querySelector('code').textContent;
      try {
        await navigator.clipboard.writeText(text);
        button.textContent = 'Copied';
      } catch {
        const range = document.createRange();
        range.selectNodeContents(button.parentElement.querySelector('code'));
        getSelection().removeAllRanges();
        getSelection().addRange(range);
        button.textContent = 'Selected';
      }
      setTimeout(() => (button.textContent = 'Copy'), 1600);
    });
  }
})();
