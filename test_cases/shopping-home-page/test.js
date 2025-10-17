// New harness signature with dependency injection
module.exports.run = async ({ page, assert }) => {
  await assert("Has an h1", async () => {
    const h1 = await page.$$eval("h1", els => els.length);
    const roleH1 = await page.$$eval("[role='heading'][aria-level='1']", els => els.length);
    return (h1 + roleH1) >= 1;
  });

  await assert("Has single h1", async () => {
    const h1 = await page.getByRole('heading', { level: 1 });
    const count = await h1.count();
    return count === 1;
  }, {type: 'BP'});

  await assert("Has at least one h2", async () => {
    const h2 = await page.getByRole('heading', { level: 2 });
    const count = await h2.count();
    return count >= 1;
  });

  await assert("Has a single banner", async () => {
    const banner = await page.getByRole('banner');
    return (await banner.count()) === 1;
  });

  await assert("Has a single maincontent", async () => {
    const main = await page.getByRole('main');
    return (await main.count()) === 1;
  });

  await assert("Has a single navigation", async () => {
    const nav = await page.getByRole('navigation');
    return (await nav.count()) === 1;
  });

  await assert("Has a single footer", async () => {
    let footer = await page.getByRole('contentinfo');
    return (await footer.count()) === 1;
  });

  return {}; // assertions collected via injected assert
};
