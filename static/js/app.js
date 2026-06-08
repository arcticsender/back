(() => {
  const token = document.querySelector('meta[name="csrf-token"]')?.content;
  if (token) {
    document.querySelectorAll('form[method="post"], form[method="POST"]').forEach((form) => {
      if (!form.querySelector('input[name="_csrf_token"]')) {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = '_csrf_token';
        input.value = token;
        form.prepend(input);
      }
    });
  }


  document.querySelectorAll('.flash').forEach((flash) => {
    const close = () => {
      flash.classList.add('is-hiding');
      setTimeout(() => flash.remove(), 180);
    };
    flash.querySelector('.flash-close')?.addEventListener('click', close);
    setTimeout(close, 2400);
  });

  document.addEventListener('click', (event) => {
    const deleteButton = event.target.closest('form.inline button');
    if (deleteButton && deleteButton.textContent.trim().toLowerCase() === 'delete') {
      if (!confirm('Delete this item?')) event.preventDefault();
    }
  });

  const canvas = document.getElementById('snow-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let width = 0;
  let height = 0;
  let flakes = [];
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function resize() {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
    const isSmall = width < 720;
    const count = reduceMotion ? 0 : Math.min(isSmall ? 34 : 82, Math.floor(width / (isSmall ? 22 : 17)));
    flakes = Array.from({ length: count }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      r: Math.random() * 2.25 + 0.65,
      s: Math.random() * 0.7 + 0.25,
      drift: Math.random() * 0.5 + 0.1,
      phase: Math.random() * Math.PI * 2,
      opacity: Math.random() * 0.50 + 0.22,
    }));
  }

  function draw() {
    ctx.clearRect(0, 0, width, height);
    flakes.forEach((f) => {
      f.phase += 0.008;
      f.y += f.s;
      f.x += Math.sin(f.phase) * f.drift;
      if (f.y > height + 8) { f.y = -8; f.x = Math.random() * width; }
      if (f.x > width + 8) f.x = -8;
      if (f.x < -8) f.x = width + 8;
      ctx.beginPath();
      ctx.fillStyle = `rgba(190, 241, 255, ${f.opacity})`;
      ctx.arc(f.x, f.y, f.r, 0, Math.PI * 2);
      ctx.fill();
    });
    if (!document.hidden) requestAnimationFrame(draw);
  }

  resize();
  window.addEventListener('resize', resize, { passive: true });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) draw(); });
  draw();
})();

(() => {
  document.querySelectorAll('.share-btn').forEach((button) => {
    button.addEventListener('click', async () => {
      const url = button.dataset.shareUrl || window.location.href;
      const title = button.dataset.shareTitle || document.title;
      try {
        if (navigator.share) {
          await navigator.share({ title, url });
        } else if (navigator.clipboard) {
          await navigator.clipboard.writeText(url);
          const old = button.innerHTML;
          button.classList.add('copied');
          if (button.classList.contains('icon-btn')) {
            button.setAttribute('aria-label', 'Link copied');
          } else {
            button.textContent = 'Link copied';
          }
          setTimeout(() => { button.innerHTML = old; button.classList.remove('copied'); }, 1600);
        }
      } catch (err) {
        console.warn('Share cancelled or failed', err);
      }
    });
  });
})();

(() => {
  document.querySelectorAll('.file-picker input[type="file"]').forEach((input) => {
    const wrap = input.closest('.file-picker');
    const name = wrap?.querySelector('.file-picker-name');
    input.addEventListener('change', () => {
      if (name) name.textContent = input.files?.[0]?.name || 'No image selected';
    });
  });

  const typeSelect = document.querySelector('select[name="gift_type"]');
  const stockField = document.querySelector('.stock-field');
  const syncStockField = () => {
    if (!typeSelect || !stockField) return;
    stockField.style.display = typeSelect.value === 'single' ? '' : 'none';
  };
  typeSelect?.addEventListener('change', syncStockField);
  syncStockField();
})();

(() => {
  const button = document.querySelector('.mobile-menu-btn');
  const drawer = document.getElementById('mobile-drawer');
  if (!button || !drawer) return;
  const open = () => {
    document.body.classList.add('mobile-menu-open');
    button.setAttribute('aria-expanded', 'true');
    drawer.setAttribute('aria-hidden', 'false');
  };
  const close = () => {
    document.body.classList.remove('mobile-menu-open');
    button.setAttribute('aria-expanded', 'false');
    drawer.setAttribute('aria-hidden', 'true');
  };
  button.addEventListener('click', () => document.body.classList.contains('mobile-menu-open') ? close() : open());
  document.querySelectorAll('[data-close-mobile-menu]').forEach((el) => el.addEventListener('click', close));
  drawer.querySelectorAll('a').forEach((link) => link.addEventListener('click', close));
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') close(); });
})();

(() => {
  const openButtons = document.querySelectorAll('.gift-modal-open');
  if (!openButtons.length) return;

  const openModal = (modal) => {
    if (!modal) return;
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('gift-modal-is-open');
    setTimeout(() => modal.querySelector('input, button, a')?.focus(), 40);
  };

  const closeModal = (modal) => {
    if (!modal) return;
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    if (!document.querySelector('.gift-modal.is-open')) {
      document.body.classList.remove('gift-modal-is-open');
    }
  };

  openButtons.forEach((button) => {
    button.addEventListener('click', (event) => {
      const modalId = button.dataset.giftModal;
      const modal = modalId ? document.getElementById(modalId) : null;
      if (!modal) return;
      event.preventDefault();
      openModal(modal);
    });
  });

  document.querySelectorAll('[data-close-gift-modal]').forEach((button) => {
    button.addEventListener('click', () => closeModal(button.closest('.gift-modal')));
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    document.querySelectorAll('.gift-modal.is-open').forEach(closeModal);
  });
})();

(() => {
  // Keep creator management controls from triggering gift-card quick-view handlers on touch devices.
  document.querySelectorAll('.owner-card-tools, .owner-card-tools button, .owner-card-tools summary, .owner-card-tools input, .owner-card-tools select, .owner-card-tools textarea').forEach((el) => {
    el.addEventListener('click', (event) => event.stopPropagation(), { passive: false });
    el.addEventListener('touchstart', (event) => event.stopPropagation(), { passive: true });
  });
})();
