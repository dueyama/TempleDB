(() => {
  const page = document.querySelector('[data-home-refresh-date]');
  if (!page || !page.dataset.homeRefreshDate) return;
  const renderedDate = page.dataset.homeRefreshDate;
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone: page.dataset.homeRefreshTimezone || 'Asia/Tokyo',
    year: 'numeric', month: '2-digit', day: '2-digit',
  });
  let reloading = false;
  let completionEdited = false;
  const keepCompletionInput = event => {
    if (event.target.closest?.('.home-service-completion')) completionEdited = true;
  };
  document.addEventListener('input', keepCompletionInput);
  document.addEventListener('change', keepCompletionInput);
  const checkDay = () => {
    if (completionEdited) return;
    if (reloading || document.visibilityState !== 'visible' || navigator.onLine === false) return;
    if (document.querySelector('dialog[open]')) return;
    const parts = Object.fromEntries(formatter.formatToParts(new Date()).map(part => [part.type, part.value]));
    const today = `${parts.year}-${parts.month}-${parts.day}`;
    if (today === renderedDate) return;
    // Avoid repeated reloads if the device clock or a cached response is stale.
    const key = 'templedb.home.day-refresh';
    try {
      if (sessionStorage.getItem(key) === today) return;
      sessionStorage.setItem(key, today);
    } catch (_) {
      // Without a persistent loop guard, leave manual refresh available.
      return;
    }
    reloading = true;
    window.location.reload();
  };
  document.addEventListener('visibilitychange', checkDay);
  document.addEventListener('close', checkDay, true);
  window.addEventListener('pageshow', checkDay);
  window.addEventListener('focus', checkDay);
  window.addEventListener('online', checkDay);
  // This only checks the date locally; no network request on the same day.
  window.setInterval(checkDay, 30000);
  checkDay();
})();
