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
        return el.hasAttribute("aria-hidden") === "true" || window.getComputedStyle(el).display === "none";
      });
      if (!isHidden) {
        return false;
      }
    }
    return true;
  });
};

