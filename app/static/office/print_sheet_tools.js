(() => {
  const defaultSelectors = {
    slot: "[data-print-sheet-slot]",
    frame: "[data-print-sheet-frame]",
  };

  function resetViewportScale(slot, frame) {
    if (!slot || !frame) {
      return;
    }
    frame.style.transform = "";
    slot.style.width = "";
    slot.style.height = "";
  }

  function fitViewportSheet(slot, frame) {
    if (!slot || !frame || window.matchMedia("print").matches) {
      return;
    }
    resetViewportScale(slot, frame);
    const availableWidth = Math.max(1, slot.parentElement.clientWidth);
    const naturalWidth = Math.max(frame.offsetWidth, frame.scrollWidth);
    const naturalHeight = Math.max(frame.offsetHeight, frame.scrollHeight);
    if (!naturalWidth || !naturalHeight) {
      return;
    }
    const scale = Math.min(1, availableWidth / naturalWidth);
    frame.style.transform = `scale(${scale})`;
    slot.style.width = `${naturalWidth * scale}px`;
    slot.style.height = `${naturalHeight * scale}px`;
  }

  function contentBoxSize(element) {
    const style = window.getComputedStyle(element);
    return {
      width: Math.max(
        1,
        element.clientWidth
          - (parseFloat(style.paddingLeft) || 0)
          - (parseFloat(style.paddingRight) || 0),
      ),
      height: Math.max(
        1,
        element.clientHeight
          - (parseFloat(style.paddingTop) || 0)
          - (parseFloat(style.paddingBottom) || 0),
      ),
    };
  }

  function fitContentToPage(page, content, layoutWidth) {
    if (!page || !content) {
      return;
    }
    content.style.removeProperty("--print-document-scale");
    content.style.removeProperty("--print-document-width");
    const available = contentBoxSize(page);
    // Keep wrapping fixed while scaling. DOM rects include the mobile viewport
    // transform; layout dimensions do not, so repeated fits remain stable.
    content.style.setProperty("--print-document-width", layoutWidth || `${available.width}px`);
    const naturalWidth = Math.max(content.scrollWidth, content.offsetWidth);
    const naturalHeight = Math.max(content.scrollHeight, content.offsetHeight);
    if (!naturalWidth || !naturalHeight) {
      return;
    }
    // Leave one CSS pixel for fractional millimetre / printer rounding.
    const scale = Math.min(1, Math.max(1, available.width - 1) / naturalWidth,
      Math.max(1, available.height - 1) / naturalHeight);
    content.style.setProperty("--print-document-scale", String(scale));
  }

  function setupPrintSheet(options = {}) {
    const slot = document.querySelector(options.slotSelector || defaultSelectors.slot);
    const frame = document.querySelector(options.frameSelector || defaultSelectors.frame);
    const page = options.pageSelector ? document.querySelector(options.pageSelector) : null;
    const content = options.contentSelector ? document.querySelector(options.contentSelector) : null;
    const fitContent = () => fitContentToPage(page, content, options.layoutWidth);
    const fitAll = () => {
      if (options.printOnly && !window.matchMedia("print").matches) {
        return;
      }
      fitContent();
      fitViewportSheet(slot, frame);
    };
    const beforePrint = () => {
      if (options.prepareClass) {
        document.body.classList.add(options.prepareClass);
      }
      resetViewportScale(slot, frame);
      fitContent();
    };

    fitAll();
    document.addEventListener("DOMContentLoaded", fitAll);
    document.fonts?.ready?.then(fitAll).catch(() => {});
    window.addEventListener("load", fitAll);
    window.addEventListener("pageshow", fitAll);
    window.addEventListener("resize", fitAll);
    window.addEventListener("orientationchange", () => window.setTimeout(fitAll, 250));
    window.visualViewport?.addEventListener("resize", fitAll);
    window.addEventListener("beforeprint", beforePrint);
    window.addEventListener("afterprint", () => {
      if (options.prepareClass) {
        document.body.classList.remove(options.prepareClass);
      }
      fitAll();
    });
  }

  window.TempleDBPrintSheet = {
    fitContentToPage,
    fitViewportSheet,
    resetViewportScale,
    setupPrintSheet,
  };
})();
