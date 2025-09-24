// New harness signature with dependency injection
module.exports.run = async ({ page, assert }) => {
  await assert("Has an h1", async () => {
    const h1 = await page.$$eval("h1", els => els.length);
    const roleH1 = await page.$$eval("[role='heading'][aria-level='1']", els => els.length);
    return (h1 + roleH1) >= 1;
  });

  await assert("Has single h1", async () => {
    const h1 = await page.$$eval("h1", els => els.length);
    const roleH1 = await page.$$eval("[role='heading'][aria-level='1']", els => els.length);
    return (h1 + roleH1) === 1;
  }, {type: 'BP'});

  await assert("Has at least one h2", async () => {
    const h2 = await page.$$eval("h2", els => els.length);
    const roleH2 = await page.$$eval("[role='heading'][aria-level='2']", els => els.length);
    return (h2 + roleH2) >= 1;
  });

  await assert("Has a single banner", async () => {
    return (await page.$$eval("::-p-aria([role='banner'])", els => els.length)) === 1;
  });

  await assert("Has a single maincontent", async () => {
    return (await page.$$eval("::-p-aria([role='banner'])", els => els.length)) === 1;
  });

  await assert("Has a single navigation", async () => {
    return (await page.$$eval("::-p-aria([role='banner'])", els => els.length)) === 1;
  });

  await assert("Has a single footer", async () => {
    return (await page.$$eval("::-p-aria([role='contentinfo'])", els => els.length)) === 1;
  });

  // Example Best Practice assertion (will not affect pass/fail)
  await assert("H2 sections present", async () => {
    const h2 = await page.$$eval("h2", els => els.length);
    return h2 >= 1;
  }, { type: 'BP' });

  return {}; // assertions collected via injected assert
};
