async function clickNav(page, key) {
  const link = page.locator(`[data-report-nav="${key}"]`);
  if (await link.count()) {
    await link.click();
  }
}

async function visibleSampleCount(card) {
  return await card.locator('.sample-card').evaluateAll((cards) =>
    cards.filter((card) => getComputedStyle(card).display !== 'none').length
  );
}

async function visibleModelGroups(card) {
  return await card.locator('[data-model-group]').evaluateAll((groups) =>
    groups
      .filter((group) => getComputedStyle(group).display !== 'none')
      .map((group) => group.getAttribute('data-model-group'))
  );
}

async function openFirstDetailCard(page) {
  const card = page.locator('[data-detail-card]').first();
  if (!(await card.evaluate((el) => el.open))) {
    await card.click();
  }
  await card.locator('[data-detail-browser]').waitFor({ state: 'visible', timeout: 10000 });
  return card;
}

module.exports.run = async ({ page, assert }) => {
  await assert('Report exposes global detailed-result filters', async () => {
    await clickNav(page, 'details');
    await page.locator('#detail-model-filter').waitFor();
    const cardCount = await page.locator('[data-detail-card]').count();
    return {
      pass: cardCount > 0,
      message: `Found ${cardCount} detail cards`,
    };
  });

  await assert('Global model filter applies when opening a card for the first time', async () => {
    await clickNav(page, 'details');
    await page.selectOption('#detail-model-filter', { label: 'Model A' });
    await page.selectOption('#detail-variant-filter', { value: 'control' });
    await page.selectOption('#detail-result-filter', { value: '' });

    const card = await openFirstDetailCard(page);
    const summaryText = (await card.locator('[data-assertion-filter-count]').textContent()) || '';
    const visibleSamples = await visibleSampleCount(card);
    const groups = await visibleModelGroups(card);

    const pass = visibleSamples === 1 && groups.length === 1 && groups[0] === 'provider/model-a';
    return {
      pass,
      message: `summary=${summaryText.trim()} visibleSamples=${visibleSamples} groups=${groups.join(',')}`,
    };
  });

  await assert('Global filters continue applying to already loaded card content', async () => {
    await clickNav(page, 'details');
    await page.selectOption('#detail-model-filter', { label: 'Model B' });
    await page.selectOption('#detail-result-filter', { label: 'Fail' });

    const card = page.locator('[data-detail-card]').first();
    const summaryText = (await card.locator('[data-assertion-filter-count]').textContent()) || '';
    const visibleSamples = await visibleSampleCount(card);
    const groups = await visibleModelGroups(card);

    const pass = visibleSamples === 1 && groups.length === 1 && groups[0] === 'provider/model-b';
    return {
      pass,
      message: `summary=${summaryText.trim()} visibleSamples=${visibleSamples} groups=${groups.join(',')}`,
    };
  });

  await assert('Conversation dialog lazy loads inside the report', async () => {
    await clickNav(page, 'details');
    await page.click('#detail-reset-filters');
    const card = await openFirstDetailCard(page);
    const modelGroup = card.locator('[data-model-group="provider/model-a"]').first();
    if (!(await modelGroup.evaluate((el) => el.open))) {
      await modelGroup.click();
    }
    const button = modelGroup.locator('.conversation-btn').first();
    await button.click();
    const dialog = card.locator('dialog[open]').first();
    await dialog.waitFor({ state: 'visible', timeout: 10000 });
    const bodyText = (await dialog.locator('.conversation-dialog-body').textContent()) || '';
    await dialog.locator('[data-closes-dialog]').click();
    return {
      pass: bodyText.includes('Build an accessible modal dialog.'),
      message: bodyText.trim().slice(0, 120),
    };
  });
};

module.exports.runAxe = async ({ page, utils }) => {
  const combinedViolations = [];

  async function collect(label, action) {
    if (action) {
      await action();
    }
    const result = await utils.runAxeOnPage(page);
    for (const violation of result.violations || []) {
      combinedViolations.push({
        ...violation,
        description: `[${label}] ${violation.description}`,
      });
    }
  }

  await collect('overview');
  await collect('control', async () => clickNav(page, 'control'));
  await collect('instructions', async () => clickNav(page, 'instructions'));
  await collect('skills', async () => clickNav(page, 'skills'));
  await collect('details', async () => {
    await clickNav(page, 'details');
    await page.click('#detail-reset-filters');
    const card = await openFirstDetailCard(page);
    const modelGroup = card.locator('[data-model-group="provider/model-a"]').first();
    if (!(await modelGroup.evaluate((el) => el.open))) {
      await modelGroup.click();
    }
  });
  await collect('conversation-dialog', async () => {
    const button = page.locator('.conversation-btn').first();
    await button.click();
    await page.locator('dialog[open] .conversation-dialog-body').waitFor({ state: 'visible', timeout: 10000 });
  });
  await page.locator('dialog[open] [data-closes-dialog]').click();
  await collect('about', async () => clickNav(page, 'about'));
  await collect('standalone-detail', async () => {
    await page.goto(new URL('report_pages/details/sample-case.html', page.url()).toString(), { waitUntil: 'load' });
    await utils.ensureAxeOnPage(page);
    const modelGroup = page.locator('[data-model-group="provider/model-a"]').first();
    if (!(await modelGroup.evaluate((el) => el.open))) {
      await modelGroup.click();
    }
  });
  await collect('standalone-conversation-dialog', async () => {
    const button = page.locator('.conversation-btn').first();
    await button.click();
    await page.locator('dialog[open] .conversation-dialog-body').waitFor({ state: 'visible', timeout: 10000 });
  });

  return { violations: combinedViolations };
};