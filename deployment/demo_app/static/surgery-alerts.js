// Scheduling state, rather than read/dismiss state, controls the persistent bell.
(() => {
  const bell = document.getElementById('pending-surgery-bell');
  if (!bell) return;
  const badge = bell.querySelector('[data-pending-count]');
  const announcement = document.getElementById('pending-surgery-announcement');
  let busy = false;
  let previous = bell.hidden ? 0 : Number(badge.textContent);
  async function refresh() {
    if (busy || document.hidden) return;
    busy = true;
    try {
      const response = await fetch('/api/surgery/pending', {cache: 'no-store', credentials: 'same-origin'});
      if (response.status === 401) {
        bell.hidden = true;
        document.body.classList.remove('has-pending-surgery');
        return;
      }
      if (!response.ok) return;
      const data = await response.json();
      if (!Number.isSafeInteger(data.count) || data.count < 0) return;
      const label = `${data.count} patient${data.count === 1 ? '' : 's'} awaiting a surgery date`;
      badge.textContent = data.count < 100 ? String(data.count) : '99+';
      bell.setAttribute('aria-label', `${label}. View pending scheduling.`);
      bell.hidden = data.count === 0;
      document.body.classList.toggle('has-pending-surgery', data.count > 0);
      if (data.count !== previous) announcement.textContent = data.count ? label : 'No surgery dates are currently pending in your workspace.';
      previous = data.count;
    } catch (_) {
      // Keep the last known reminder if a request fails; a network error is not a booking.
    } finally {
      busy = false;
    }
  }
  window.setInterval(refresh, 30000);
  window.addEventListener('focus', refresh);
  document.addEventListener('visibilitychange', refresh);
  window.addEventListener('pageshow', refresh);
})();
