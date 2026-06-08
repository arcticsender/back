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
    const count = reduceMotion ? 0 : Math.min(isSmall ? 28 : 70, Math.floor(width / (isSmall ? 24 : 18)));
    flakes = Array.from({ length: count }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      r: Math.random() * 2.4 + 0.6,
      s: Math.random() * 0.7 + 0.25,
      drift: Math.random() * 0.5 + 0.1,
      phase: Math.random() * Math.PI * 2,
      opacity: Math.random() * 0.55 + 0.18,
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
          const old = button.textContent;
          button.textContent = 'Link copied';
          button.classList.add('copied');
          setTimeout(() => { button.textContent = old; button.classList.remove('copied'); }, 1600);
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
