(() => {
  const rowsContainer = document.querySelector("[data-payment-rows]");
  if (!rowsContainer) return;
  const scheduledDate = document.getElementById("id_scheduled_date");
  const completedOn = document.getElementById("id_completed_on");
  const addButton = document.querySelector("[data-add-payment-row]");
  const template = document.getElementById("payment-empty-form-template");
  const totalForms = document.getElementById("id_payments-TOTAL_FORMS");

  function syncBlankPaymentDates(root = rowsContainer) {
    const nextValue = scheduledDate?.value || completedOn?.value || "";
    if (!nextValue) return;
    // Query the current rows so dates added after initial setup are included.
    root.querySelectorAll('input[name$="-received_on"]').forEach((input) => {
      if (!input.value) {
        input.value = nextValue;
      }
    });
  }

  if (scheduledDate) {
    scheduledDate.addEventListener("change", () => syncBlankPaymentDates());
  }
  if (completedOn) {
    completedOn.addEventListener("change", () => syncBlankPaymentDates());
  }
  syncBlankPaymentDates();

  if (addButton && template && totalForms) {
    addButton.addEventListener("click", () => {
      const index = Number(totalForms.value || "0");
      const wrapper = document.createElement("div");
      wrapper.innerHTML = template.innerHTML.replaceAll("__prefix__", String(index));
      const row = wrapper.firstElementChild;
      if (!row) return;
      rowsContainer.appendChild(row);
      totalForms.value = String(index + 1);
      syncBlankPaymentDates(row);
    });
  }
})();
