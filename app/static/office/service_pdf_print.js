(() => {
  const button = document.getElementById("service-pdf-direct-print");
  const status = document.getElementById("service-pdf-print-status");
  if (!button || !status) return;
  const controller = new AbortController();
  let frame;
  let objectUrl;
  let ready = false;
  let disposed = false;
  let readyTimer;
  const fallback = "直接印刷を準備できませんでした。「PDFを開く・印刷」から印刷してください。";
  const timeout = setTimeout(() => {
    if (!ready) {
      controller.abort();
      status.textContent = fallback;
    }
  }, 30000);
  function fail() {
    clearTimeout(timeout);
    clearTimeout(readyTimer);
    ready = false;
    button.disabled = true;
    status.textContent = fallback;
  }
  button.addEventListener("click", () => {
    if (!ready) return;
    try {
      // Keep this synchronous with the user's tap for mobile Safari.
      frame.contentWindow.focus();
      frame.contentWindow.print();
      status.textContent = "印刷画面が出ない場合や白紙の場合は、「PDFを開く・印刷」をお使いください。";
    } catch (_) {
      fail();
    }
  });
  async function prepare() {
    try {
      const response = await fetch(button.dataset.pdfUrl, {
        credentials: "same-origin", cache: "no-store", signal: controller.signal,
      });
      if (!response.ok || !(response.headers.get("Content-Type") || "").startsWith("application/pdf")) {
        throw new Error("PDF unavailable");
      }
      const blob = await response.blob();
      if (disposed || controller.signal.aborted) return;
      objectUrl = URL.createObjectURL(blob);
      frame = document.createElement("iframe");
      frame.title = "直接印刷用PDF";
      frame.tabIndex = -1;
      frame.setAttribute("aria-hidden", "true");
      // A rendered, offscreen frame: display:none can prevent PDF printing.
      frame.style.cssText = "position:fixed;left:-10000px;top:0;width:794px;height:1123px;border:0;pointer-events:none;";
      frame.addEventListener("load", () => {
        readyTimer = setTimeout(() => {
          if (disposed || controller.signal.aborted) return;
          clearTimeout(timeout);
          ready = true;
          button.disabled = false;
          status.textContent = "「直接印刷」を押してください。印刷画面が出ない場合は「PDFを開く・印刷」をお使いください。";
        }, 1000);
      }, { once: true });
      frame.addEventListener("error", fail, { once: true });
      frame.src = objectUrl;
      document.body.appendChild(frame);
    } catch (_) {
      if (!disposed) fail();
    }
  }
  window.addEventListener("pagehide", (event) => {
    if (event.persisted) return;
    disposed = true;
    controller.abort();
    clearTimeout(timeout);
    clearTimeout(readyTimer);
    frame?.remove();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  });
  prepare();
})();
