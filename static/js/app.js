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


  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  document.querySelectorAll('.flash').forEach((flash) => {
    const close = () => {
      flash.classList.add('is-hiding');
      if (prefersReducedMotion) flash.remove();
      else setTimeout(() => flash.remove(), 180);
    };
    flash.querySelector('.flash-close')?.addEventListener('click', close);
    if (!prefersReducedMotion) setTimeout(close, 4200);
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
  let frame = 0;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function resize() {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
    const isSmall = width < 720;
    const count = reduceMotion ? 0 : Math.min(isSmall ? 24 : 58, Math.floor(width / (isSmall ? 30 : 24)));
    flakes = Array.from({ length: count }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      r: Math.random() * 2.45 + 0.75,
      s: Math.random() * 0.7 + 0.25,
      drift: Math.random() * 0.5 + 0.1,
      phase: Math.random() * Math.PI * 2,
      opacity: Math.random() * 0.54 + 0.28,
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
    if (!document.hidden && !reduceMotion) frame = requestAnimationFrame(draw);
  }

  resize();
  window.addEventListener('resize', resize, { passive: true });
  document.addEventListener('visibilitychange', () => { if (document.hidden) { if (frame) cancelAnimationFrame(frame); frame = 0; } else if (!reduceMotion && !frame) draw(); });
  if (!reduceMotion) draw();
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
  const button = document.querySelector('.mobile-bottom-nav .mobile-menu-btn');
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

(() => {
  document.querySelectorAll('[data-fill-amount][data-fill-target]').forEach((button) => {
    button.addEventListener('click', () => {
      const input = document.getElementById(button.dataset.fillTarget);
      if (!input) return;
      input.value = button.dataset.fillAmount;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      button.closest('.smart-amounts')?.querySelectorAll('.smart-amount-btn').forEach((btn) => btn.classList.remove('is-selected'));
      button.classList.add('is-selected');
    });
  });
})();


// Copy creator page links and other small share actions.
document.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-copy-text]');
  if (!button) return;
  const value = button.getAttribute('data-copy-text') || '';
  try {
    await navigator.clipboard.writeText(value);
    const previous = button.textContent;
    button.textContent = 'Link copied';
    window.setTimeout(() => { button.textContent = previous; }, 1800);
  } catch (_) {
    window.prompt('Copy your creator page link:', value);
  }
});


// Wishlist ordering: touch-and-hold on mobile, drag handle on desktop, keyboard accessible.
(() => {
  const table = document.querySelector('[data-wishlist-sort]');
  if (!table) return;
  const feedback = document.querySelector('[data-order-feedback]');
  const rows = () => Array.from(table.querySelectorAll('tr[data-item-id]'));
  const setFeedback = message => { if (feedback) feedback.textContent = message; };
  let saving = false, pendingSave = false, lastSaved = rows().map(r => r.dataset.itemId).join(',');
  async function save() {
    if (saving) { pendingSave = true; return; }
    const current = rows().map(r => r.dataset.itemId).join(',');
    if (current === lastSaved) return;
    saving = true;
    setFeedback('Saving gift order…');
    const token = document.querySelector('meta[name="csrf-token"]')?.content || '';
    try {
      const response = await fetch('/wishlist/reorder', {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type':'application/json','X-CSRF-Token':token},
        body: JSON.stringify({item_ids:rows().map(r => Number(r.dataset.itemId))})
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.ok !== true) throw new Error(result.error || `Server returned ${response.status}`);
      lastSaved = current;
      setFeedback('Saved. Your public wishlist now uses this order.');
    } catch (error) {
      setFeedback('Could not save: ' + (error.message || 'Please try again.'));
    } finally {
      saving = false;
      if (pendingSave) { pendingSave = false; void save(); }
    }
  }
  // Relative moves are also keyboard accessible (Alt+Up/Down).
  function move(row, direction) {
    const all = rows(), index = all.indexOf(row), neighbour = all[index + direction];
    if (!neighbour) return;
    row.parentNode.insertBefore(row, direction < 0 ? neighbour : neighbour.nextSibling);
    void save();
  }
  let gesture = null, hold = 0;
  const clearHold = () => { clearTimeout(hold); hold = 0; };
  function endGesture(cancelled = false) {
    clearHold();
    if (!gesture) return;
    const {row, moved, active} = gesture;
    gesture = null;
    row.classList.remove('is-touch-dragging');
    document.body.classList.remove('gift-reordering');
    document.removeEventListener('pointermove', onMove);
    document.removeEventListener('pointerup', onUp);
    document.removeEventListener('pointercancel', onCancel);
    if (active && moved) void save();
    else if (active && !cancelled) setFeedback('Move the gift above or below another gift, then release.');
  }
  function onMove(event) {
    const drag = gesture;
    if (!drag || event.pointerId !== drag.pointerId) return;
    if (!drag.active) {
      // A finger moving to scroll before the long press must not reorder.
      if (Math.abs(event.clientY - drag.startY) > 12) endGesture(true);
      return;
    }
    event.preventDefault();
    const all = rows().filter(row => row !== drag.row && !row.hidden);
    const before = all.find(row => event.clientY < row.getBoundingClientRect().top + row.getBoundingClientRect().height / 2);
    const previous = rows().map(row => row.dataset.itemId).join(',');
    if (before) drag.row.parentNode.insertBefore(drag.row, before);
    else if (all.length) drag.row.parentNode.insertBefore(drag.row, all[all.length-1].nextSibling);
    if (rows().map(row => row.dataset.itemId).join(',') !== previous) {
      drag.moved = true;
      setFeedback('New position selected. Release to save.');
    }
    if (event.clientY < 95) window.scrollBy(0, -12);
    else if (event.clientY > window.innerHeight - 130) window.scrollBy(0, 12);
  }
  function onUp(event) { if (gesture && event.pointerId === gesture.pointerId) endGesture(false); }
  function onCancel(event) { if (gesture && event.pointerId === gesture.pointerId) endGesture(true); }
  rows().forEach(row => {
    const grip = row.querySelector('[data-gift-drag-handle]');
    if (grip) {
      grip.addEventListener('pointerdown', event => {
        if (!event.isPrimary || gesture || saving) return;
        if (event.pointerType === 'mouse' && event.button !== 0) return;
        event.preventDefault();
        gesture = {pointerId:event.pointerId, row, startY:event.clientY, active:false, moved:false};
        document.addEventListener('pointermove', onMove, {passive:false});
        document.addEventListener('pointerup', onUp);
        document.addEventListener('pointercancel', onCancel);
        clearHold();
        const pointerId = event.pointerId;
        hold = window.setTimeout(() => {
          if (!gesture || gesture.pointerId !== pointerId) return;
          gesture.active = true;
          row.classList.add('is-touch-dragging');
          document.body.classList.add('gift-reordering');
          setFeedback('Now slide the gift up or down. Release to save.');
        }, event.pointerType === 'mouse' ? 0 : 250);
      });
      grip.addEventListener('contextmenu', event => event.preventDefault());
      grip.addEventListener('keydown', event => {
        if (!['ArrowUp','ArrowDown'].includes(event.key)) return;
        event.preventDefault(); move(row, event.key === 'ArrowUp' ? -1 : 1);
      });
    }
    row.querySelectorAll('[data-move]').forEach(button => button.addEventListener('click', () => move(row, button.dataset.move === 'up' ? -1 : 1)));
    row.addEventListener('keydown', event => {
      if (!event.altKey || !['ArrowUp','ArrowDown'].includes(event.key)) return;
      event.preventDefault(); move(row, event.key === 'ArrowUp' ? -1 : 1);
    });
    row.tabIndex = 0;
  });
  // Native desktop drag and drop is retained as a secondary interaction.
  let dragged = null;
  rows().forEach(row => {
    row.addEventListener('dragstart', event => {
      if (gesture || saving) {event.preventDefault();return;}
      dragged = row; row.classList.add('is-dragging');
      if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
    });
    row.addEventListener('dragover', event => {
      if (!dragged || dragged === row) return;
      event.preventDefault();
      const rect = row.getBoundingClientRect();
      row.parentNode.insertBefore(dragged, event.clientY > rect.top + rect.height / 2 ? row.nextSibling : row);
    });
    row.addEventListener('dragend', () => {
      row.classList.remove('is-dragging');
      if (!dragged) return;
      dragged = null; void save();
    });
  });
})();

// Dismiss an announcement without permanently hiding a newly edited announcement.
(() => {
  const banner = document.querySelector('.global-announcement');
  if (!banner) return;
  const key = 'announcement-dismissed-v2';
  const message = banner.querySelector('.announcement-message')?.textContent?.trim() || '';
  try { if (sessionStorage.getItem(key) === message) banner.hidden = true; } catch (_) {}
  banner.querySelector('[data-dismiss-announcement]')?.addEventListener('click', () => {
    banner.hidden = true;
    try { sessionStorage.setItem(key, message); } catch (_) {}
  });
})();

// Mobile notification popover: accessible state, outside-click dismissal and Escape.
(() => {
 const panel=document.getElementById('mobile-notification-panel');
 const trigger=document.querySelector('[data-toggle-notifications]');
 if(!panel||!trigger)return;
 const close=()=>{panel.classList.remove('is-open');panel.setAttribute('aria-hidden','true');panel.inert=true;trigger.setAttribute('aria-expanded','false');};
 const open=()=>{document.body.classList.remove('mobile-menu-open');document.querySelector('.mobile-menu-btn')?.setAttribute('aria-expanded','false');document.getElementById('mobile-drawer')?.setAttribute('aria-hidden','true');panel.inert=false;panel.classList.add('is-open');panel.setAttribute('aria-hidden','false');trigger.setAttribute('aria-expanded','true');panel.querySelector('[data-close-notifications]')?.focus();};
 trigger.addEventListener('click',()=>panel.classList.contains('is-open')?close():open());
 panel.querySelector('[data-close-notifications]')?.addEventListener('click',()=>{close();trigger.focus();});
 document.addEventListener('pointerdown',e=>{if(!panel.contains(e.target)&&!trigger.contains(e.target))close();});
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&panel.classList.contains('is-open')){close();trigger.focus();}});
})();

// Client-side wishlist discovery; no requests or changes to checkout behavior.
(() => {
 const root=document.querySelector('[data-gift-discovery]'); if(!root)return;
 const search=root.querySelector('[data-gift-search]');
 const filters=[...root.querySelectorAll('[data-gift-filter]')];
 const entries=[...document.querySelectorAll('[data-gift-entry]')];
 const count=root.querySelector('[data-gift-count]');
 const sort=root.querySelector('[data-gift-client-sort]');
 const grid=document.querySelector('[data-gift-grid]');
 const originalOrder=new Map(entries.map((entry,index)=>[entry,index]));
 const empty=document.querySelector('[data-gift-empty]');
 let active='all';
 const update=()=>{
  const query=(search.value||'').trim().toLocaleLowerCase();let visible=0;
  entries.forEach(entry=>{const show=(active==='all'||entry.dataset.giftKind===active)&&(!query||(entry.dataset.giftTitle||'').includes(query));entry.hidden=!show;if(show)visible++;});
  if(count)count.textContent=`${visible} ${visible===1?'gift':'gifts'} shown`;
  if(empty)empty.hidden=visible!==0;
 };
 const sortGifts=()=>{
  if(!sort||!grid)return;
  const ordered=[...entries].sort((a,b)=>{
   if(sort.value==='price-low')return Number(a.dataset.giftPrice)-Number(b.dataset.giftPrice);
   if(sort.value==='price-high')return Number(b.dataset.giftPrice)-Number(a.dataset.giftPrice);
   if(sort.value==='name')return (a.dataset.giftTitle||'').localeCompare(b.dataset.giftTitle||'');
   if(sort.value==='goal-progress')return Number(b.dataset.giftProgress)-Number(a.dataset.giftProgress);
   return originalOrder.get(a)-originalOrder.get(b);
  });
  ordered.forEach(entry=>grid.appendChild(entry));
 };
 sort?.addEventListener('change',sortGifts);
 search.addEventListener('input',update);
 filters.forEach(button=>button.addEventListener('click',()=>{active=button.dataset.giftFilter;filters.forEach(option=>{const selected=option===button;option.classList.toggle('is-active',selected);option.setAttribute('aria-pressed',String(selected));});update();}));
 document.querySelector('[data-gift-reset]')?.addEventListener('click',()=>{search.value='';filters[0]?.click();search.focus();});
 update();
})();

// Localized display for UTC campaign timestamps; server remains the authority.
document.querySelectorAll('[data-local-datetime]').forEach(node => {
 const input=node.dataset.localDatetime; if(!input)return;
 const date=new Date(input); if(Number.isNaN(date.getTime()))return;
 node.dateTime=date.toISOString();
 node.textContent=new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short',timeZoneName:'short'}).format(date);
});
// Confirm destructive user actions without intercepting payment or checkout forms.
document.querySelectorAll('form[data-confirm-submit]').forEach(form=>{
 form.addEventListener('submit', event=>{if(!window.confirm(form.dataset.confirmSubmit||'Are you sure?'))event.preventDefault();});
});


// Fast, local-only gift management filtering. No payment or server requests.
(() => {
  const search=document.querySelector('[data-dashboard-gift-search]');
  const status=document.querySelector('[data-dashboard-gift-status]');
  if(!search||!status)return;
  const rows=[...document.querySelectorAll('[data-dashboard-gift-row]')];
  const count=document.querySelector('[data-dashboard-gift-count]');
  const empty=document.querySelector('[data-dashboard-gift-empty]');
  const update=()=>{
    const term=search.value.trim().toLocaleLowerCase(); let visible=0;
    for(const row of rows){
      const matched=(!term||row.dataset.giftName.includes(term)) && (status.value==='all'||row.dataset.giftVisibility===status.value);
      row.hidden=!matched;
      if(matched)visible++;
    }
    if(count)count.textContent=`${visible} of ${rows.length} gifts`;
    if(empty)empty.hidden=visible!==0;
  };
  search.addEventListener('input',update);
  status.addEventListener('change',update);
  update();
})();

// Progressive enhancement: native sharing on supported mobile devices.
// Existing clipboard buttons continue to work without Web Share support.
document.querySelectorAll('[data-native-share]').forEach(button => {
  if(!navigator.share){button.hidden=true;return;}
  button.addEventListener('click', async () => {
    try { await navigator.share({title:button.dataset.shareTitle||document.title,url:button.dataset.shareUrl||location.href}); }
    catch(error) { if(error?.name!=='AbortError') console.warn('Share unavailable'); }
  });
});
