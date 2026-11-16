(() => {
  const key = "templedb-service-link-horizon-draft";
  const horizonNames = new Set(["show_3_year_links", "show_10_year_links"]);

  function capture(form, destination, now) {
    return {
      destination, expires: now + 120000,
      paymentTotal: Number(form.elements.namedItem("payments-TOTAL_FORMS")?.value || 0),
      fields: Array.from(form.elements).filter(field => (
        field.name && !field.disabled && !horizonNames.has(field.name)
        && field.name !== "csrfmiddlewaretoken"
        && !["submit", "button", "file"].includes(field.type)
      )).map(field => ({ name: field.name, type: field.type, value: field.value, checked: field.checked })),
    };
  }

  function restore(form, draft, destination, now) {
    if (!draft || draft.destination !== destination || draft.expires < now) return;
    const total = form.elements.namedItem("payments-TOTAL_FORMS");
    const add = form.querySelector("[data-add-payment-row]");
    while (add && total && Number(total.value) < Math.min(draft.paymentTotal, 1000)) {
      const before = total.value;
      add.click();
      if (total.value === before) break;
    }
    draft.fields.forEach(saved => {
      Array.from(form.elements).filter(field => (
        field.name === saved.name && !field.disabled && field.type === saved.type
        && field.name !== "csrfmiddlewaretoken" && !horizonNames.has(field.name)
        && !["submit", "button", "file"].includes(field.type)
      )).forEach(field => {
        if (["checkbox", "radio"].includes(field.type)) {
          if (field.value === saved.value) field.checked = saved.checked;
        } else {
          field.value = saved.value;
        }
      });
    });
  }

  function start(document, window) {
    const toggles = Array.from(document.querySelectorAll("[data-link-horizon-toggle]"));
    const form = toggles[0]?.form;
    if (!form) return;
    // One navigation only: never restore an old draft on a later unrelated visit.
    try {
      const raw = window.sessionStorage.getItem(key);
      window.sessionStorage.removeItem(key);
      if (raw) restore(form, JSON.parse(raw), window.location.href, Date.now());
    } catch (_error) { /* A damaged/expired draft never prevents editing. */ }
    toggles.forEach(toggle => toggle.addEventListener("change", () => {
      const url = new URL(window.location.href);
      toggles.forEach(item => {
        const parameter = item.getAttribute("data-link-horizon-query-param") || item.name;
        if (item.checked) url.searchParams.set(parameter, "1");
        else url.searchParams.delete(parameter);
      });
      try {
        window.sessionStorage.setItem(key, JSON.stringify(capture(form, url.toString(), Date.now())));
      } catch (_error) {
        toggle.checked = !toggle.checked;
        window.alert("候補範囲を切り替えられませんでした。入力内容はそのまま残っています。");
        return;
      }
      window.location.assign(url.toString());
    }));
  }

  if (typeof module !== "undefined" && module.exports) module.exports = { capture, restore, start };
  else start(document, window);
})();
