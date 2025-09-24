// New harness signature: module.exports.run = async ({ page, assert }) => { ... }
module.exports.run = async ({ page, assert }) => {
  await assert("Has a button with aria-expanded", async () => {
    const count = await page.$$eval("button[aria-expanded]", els => els.length);
    return !!count;
  });
  return {}; // assertions collected via injected assert
};
