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
