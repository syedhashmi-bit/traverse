/* Traverse — client-side helpers */

// ── Theme toggle ──────────────────────────────────────────────────────────────
(function () {
  const STORAGE_KEY = 'traverse-theme';
  function applyTheme(theme) {
    document.body.classList.toggle('theme-light', theme === 'light');
    document.body.classList.toggle('theme-dark',  theme !== 'light');
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.textContent = theme === 'light' ? '☀' : '☾';
  }
  const saved = localStorage.getItem(STORAGE_KEY) || 'dark';
  applyTheme(saved);
  document.addEventListener('DOMContentLoaded', () => {
    applyTheme(localStorage.getItem(STORAGE_KEY) || 'dark');
    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.addEventListener('click', () => {
        const next = document.body.classList.contains('theme-light') ? 'dark' : 'light';
        localStorage.setItem(STORAGE_KEY, next);
        applyTheme(next);
      });
    }
  });
})();

// Copy-to-clipboard
function copyText(text, btn) {
  const isIcon = btn && btn.classList.contains('copy-icon-btn');
  const orig   = btn.textContent;
  function feedback() {
    if (isIcon) {
      btn.textContent = '✓';
      btn.classList.add('copied');
      setTimeout(() => {
        btn.textContent = orig || '⎘';
        btn.classList.remove('copied');
      }, 2000);
    } else {
      btn.textContent = 'Copied!';
      btn.style.background = 'var(--success)';
      btn.style.color = '#fff';
      setTimeout(() => {
        btn.textContent = orig;
        btn.style.background = '';
        btn.style.color = '';
      }, 1800);
    }
  }
  function fallback() {
    const el = document.createElement('textarea');
    el.value = text;
    el.style.position = 'fixed';
    el.style.opacity = '0';
    document.body.appendChild(el);
    el.select();
    document.execCommand('copy');
    document.body.removeChild(el);
    feedback();
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(feedback).catch(fallback);
  } else {
    fallback();
  }
}

// Confirm delete forms
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('submit', e => {
      if (!confirm(el.dataset.confirm)) {
        e.preventDefault();
      }
    });
  });

  // Auto-dismiss flash messages after 5s
  setTimeout(() => {
    document.querySelectorAll('.flash').forEach(f => {
      f.style.transition = 'opacity 0.5s';
      f.style.opacity = '0';
      setTimeout(() => f.remove(), 500);
    });
  }, 5000);

  // Mobile sidebar hamburger
  const hamburger = document.getElementById('hamburger');
  const overlay   = document.getElementById('sidebar-overlay');
  if (hamburger) {
    hamburger.addEventListener('click', () => document.body.classList.toggle('sidebar-open'));
  }
  if (overlay) {
    overlay.addEventListener('click', () => document.body.classList.remove('sidebar-open'));
  }
  document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', () => document.body.classList.remove('sidebar-open'));
  });
});

// ── Sound alert toggle (Web Audio API tones) ──────────────────────
(function () {
  const KEY = 'traverse-sound-enabled';
  let enabled = localStorage.getItem(KEY) === '1';
  let audioCtx = null;

  function ensureCtx() {
    if (audioCtx) return audioCtx;
    try {
      const Ctor = window.AudioContext || window.webkitAudioContext;
      if (!Ctor) return null;
      audioCtx = new Ctor();
    } catch (e) { return null; }
    return audioCtx;
  }
  function tone(freq) {
    const ctx = ensureCtx();
    if (!ctx) return;
    if (ctx.state === 'suspended') ctx.resume().catch(() => {});
    const osc  = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.1, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 0.3);
  }
  function updateBtn() {
    const btn = document.getElementById('sound-toggle');
    if (!btn) return;
    btn.textContent = enabled ? '🔔' : '🔕';
    btn.title = enabled ? 'Sound alerts: on (click to mute)' : 'Sound alerts: off (click to enable)';
  }

  window.traverseSound = {
    play(eventType) {
      if (!enabled) return;
      if (!('Notification' in window) || Notification.permission !== 'granted') return;
      tone(eventType === 'connected' ? 880 : 440);
    },
    isEnabled() { return enabled; },
    set(on) {
      enabled = !!on;
      localStorage.setItem(KEY, enabled ? '1' : '0');
      updateBtn();
    },
  };

  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('sound-toggle');
    if (!btn) return;
    updateBtn();
    btn.addEventListener('click', () => {
      const next = !enabled;
      window.traverseSound.set(next);
      if (next) {
        // First click after enabling — unlock audio with a tiny test tone
        const ctx = ensureCtx();
        if (ctx && ctx.state === 'suspended') ctx.resume().catch(() => {});
        tone(880);
      }
    });
  });
})();

// ── Browser push notifications + sound hook ───────────────────────
(function () {
  // Only run on authenticated pages (sidebar present)
  if (!document.querySelector('aside.sidebar')) return;
  if (!('Notification' in window)) return;

  const PERM_ASKED_KEY = 'traverse-notify-asked';
  const DEVICE_ICONS   = {phone:'📱', laptop:'💻', desktop:'🖥️', tablet:'📟', router:'🖧', other:'◈'};

  // Ask permission once, after a small delay to feel less intrusive
  function maybeAskPermission() {
    if (Notification.permission !== 'default') return;
    if (localStorage.getItem(PERM_ASKED_KEY)) return;
    setTimeout(() => {
      if (Notification.permission !== 'default') return;
      Notification.requestPermission().finally(() => {
        localStorage.setItem(PERM_ASKED_KEY, '1');
      });
    }, 4000);
  }
  maybeAskPermission();

  let lastEventId = null;

  function fire(ev) {
    const icon = DEVICE_ICONS[ev.peer_device] || '◈';
    const verb = ev.event_type === 'connected' ? 'connected' : 'disconnected';
    const body = `${icon} ${ev.peer_name} ${verb}`;
    if (Notification.permission === 'granted') {
      try {
        new Notification('traverse', {
          body: body,
          icon: '/static/img/app.png',
          tag:  'traverse-evt-' + ev.id,
        });
      } catch (e) { /* swallow — some browsers throw on rapid spam */ }
    }
    // Sound (only if F7 toggle enabled and notif permission granted)
    if (window.traverseSound && typeof window.traverseSound.play === 'function') {
      window.traverseSound.play(ev.event_type);
    }
  }

  function poll() {
    fetch('/api/events/latest', { credentials: 'same-origin' })
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (!d || !Array.isArray(d.events)) return;
        const events = d.events;
        if (lastEventId === null) {
          // First poll — set baseline; don't replay history as fresh notifications
          lastEventId = events.length > 0 ? events[0].id : 0;
          return;
        }
        const fresh = events.filter(e => e.id > lastEventId);
        if (fresh.length === 0) return;
        // events come newest-first; fire in chronological order
        fresh.slice().reverse().forEach(fire);
        lastEventId = events[0].id;
      })
      .catch(() => {});
  }
  poll();
  setInterval(poll, 60000);
})();
