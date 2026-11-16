(() => {
  function createLoader(replacePanelFromHtml) {
    let generation = 0;

    return async function loadHouseholdPanel(url, {
      pushHistory = true, preservedState = null, reloadOnFailure = false,
    } = {}) {
      const requestGeneration = ++generation;
      try {
        const response = await window.fetch(url, {
          headers: { "X-Requested-With": "XMLHttpRequest" },
          credentials: "same-origin",
        });
        if (!response.ok) {
          throw new Error("panel fetch failed");
        }
        const html = await response.text();
        if (requestGeneration !== generation) {
          return;
        }
        if (!replacePanelFromHtml(html, preservedState)) {
          throw new Error("panel swap failed");
        }
        if (pushHistory && url !== window.location.href) {
          window.history.pushState({ householdBrowserPartial: true }, "", url);
        }
      } catch (_error) {
        // A stale failure must not navigate away from a newer selection.
        if (requestGeneration !== generation) {
          return;
        }
        if (reloadOnFailure) {
          window.location.reload();
        } else {
          window.location.assign(url);
        }
      }
    };
  }

  window.TempleDBHouseholdNavigation = { createLoader };
})();
