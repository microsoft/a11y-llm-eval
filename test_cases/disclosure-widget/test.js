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

  await assert("Collapsed content is hidden from assistive technology", async () => {
    for (const example of examples) {
      if (!await example.$("button[aria-expanded=false], [role='button'][aria-expanded=false]")) {
        // Only check button implementations
        continue;
      }
      
      let isHidden = await example.$eval(".details", el => {
        // Use axe-core's isVisible util to determine if hidden from sighted users but available to AT
        let isVisuallyHidden = !window.axe.commons.dom.isVisible(el, false, true);
        let isScreenReaderHidden = !window.axe.commons.dom.isVisible(el, true, true);
        return isVisuallyHidden && isScreenReaderHidden;
      });

      if (!isHidden) {
        return false;
      }
    }
    return true;
  });
};

