// New harness signature: module.exports.run = async ({ page, assert }) => { ... }
module.exports.run = async ({ page, assert }) => {
  const examples = await page.$$(".example");

  const hasValidSemantics = async (example) => {
    if (await example.$("button[aria-expanded], [role='button'][aria-expanded]")) {
      return true;
    }
    if (await example.$("details summary")) {
      return true;
    }
    return false;
  }

  await assert("All examples have a valid semantics", async () => {
    for (const example of examples) {
      if (! await hasValidSemantics(example)) {
        return false;
      }
    }
    return true;
  });

  await assert("Collapsed content is hidden from everyone", async () => {
    let applicableExamples = 0;

    for (const example of examples) {
      if (!await example.$("button[aria-expanded=false], [role='button'][aria-expanded=false]")) {
        // Only check button implementations
        continue;
      }

      applicableExamples += 1;
      
      let isHidden = await example.$eval(".details", el => {
        const virtualNode = window.axe.utils.getNodeFromTree(el);
        const hasNoContentBox = el.clientHeight === 0;
        const style = window.getComputedStyle(el);
        const clipsOverflow = /(hidden|clip)/.test(`${style.overflow} ${style.overflowX} ${style.overflowY}`);
        const isVisuallyHidden = !window.axe.commons.dom.isVisible(el, false, true)
          || (hasNoContentBox && clipsOverflow);
        const isScreenReaderHidden = !window.axe.commons.dom.isVisibleToScreenReaders(virtualNode);
        return isVisuallyHidden && isScreenReaderHidden;
      });

      if (!isHidden) {
        return false;
      }
    }

    if (applicableExamples === 0) {
      return { status: 'na', message: 'No button-based disclosure widgets found' };
    }

    return true;
  });
};

