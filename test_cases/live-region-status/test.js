/**
 * Status live-region accessibility assertions.
 *
 * Routine, non-urgent status updates ("Saving…", "Saved") should be announced
 * with a *polite* live region. A common defect is using an *assertive* region
 * (aria-live="assertive" or role="alert"), which interrupts whatever the screen
 * reader is currently saying, or injecting the region only when the update
 * happens (so it is never announced). axe-core does not flag assertive-vs-polite
 * urgency, so it is checked here.
 *
 * Grounded in the "assertive-live-region-review" anti-pattern
 * (WCAG SC 4.1.3 — Status Messages; Class II — Live Region Urgency
 * Miscalibration). Case study: videojs/video.js#9178.
 */

const LIVE_SELECTOR = '[aria-live], [role="status"], [role="alert"], [role="log"], output';

const collectLiveRegions = async (page) =>
  page.evaluate((sel) => {
    const politeness = (el) => {
      const live = (el.getAttribute('aria-live') || '').toLowerCase();
      const role = (el.getAttribute('role') || '').toLowerCase();
      if (live === 'assertive' || role === 'alert') return 'assertive';
      if (live === 'polite' || role === 'status' || role === 'log' || el.tagName.toLowerCase() === 'output') return 'polite';
      if (live === 'off') return 'off';
      return 'unknown';
    };
    const isHidden = (el) => {
      if (el.getAttribute('aria-hidden') === 'true') return true;
      const cs = window.getComputedStyle(el);
      return cs.display === 'none' || cs.visibility === 'hidden';
    };
    return Array.from(document.querySelectorAll(sel)).map((el) => ({
      role: el.getAttribute('role') || el.tagName.toLowerCase(),
      ariaLive: el.getAttribute('aria-live'),
      politeness: politeness(el),
      hidden: isHidden(el),
      isSaveStatus: el.classList.contains('save-status') || Boolean(el.closest('.save-status')),
      text: (el.textContent || '').replace(/[\s ]+/g, ' ').trim(),
    }));
  }, LIVE_SELECTOR);

// Click a non-submit button to trigger the status update (the "Save" button).
const triggerUpdate = async (page) => {
  const buttons = page.locator('button, [role="button"]');
  const count = await buttons.count().catch(() => 0);
  for (let i = 0; i < count; i += 1) {
    const el = buttons.nth(i);
    const type = (await el.getAttribute('type').catch(() => '')) || '';
    const text = ((await el.innerText().catch(() => '')) || '').toLowerCase();
    if (type === 'submit' || /submit/.test(text)) continue;
    await el.click().catch(() => {});
    await page.waitForTimeout(60);
    return;
  }
};

module.exports.run = async ({ page, assert, utils }) => {
  // Snapshot live regions present at load, before any interaction.
  const loadRegions = await collectLiveRegions(page);

  await assert('A status live region is present on load', async () => {
    if (loadRegions.length > 0) {
      return { pass: true, message: `Found ${loadRegions.length} live region(s) present at load` };
    }
    return {
      pass: false,
      message:
        'No ARIA live region (aria-live / role=status|alert|log / output) is present at load. ' +
        'A region injected only when the update happens is often not announced.',
    };
  });

  await triggerUpdate(page);
  await page.waitForTimeout(60);
  const after = await collectLiveRegions(page);

  await assert('Routine status updates use a polite live region, not assertive', async () => {
    if (after.length === 0) return { pass: false, message: 'No live region present after a status update' };
    // Prefer the region that carries the save status, else any live region.
    const statusRegions = after.filter((r) => r.isSaveStatus);
    const pool = statusRegions.length ? statusRegions : after;
    const polite = pool.filter((r) => r.politeness === 'polite');
    const assertive = pool.filter((r) => r.politeness === 'assertive');
    if (polite.length > 0 && assertive.length === 0) {
      return { pass: true, message: 'Routine status updates are announced via a polite live region' };
    }
    if (assertive.length > 0) {
      return {
        pass: false,
        message:
          'Routine status updates use an assertive live region (aria-live="assertive" or role="alert"), ' +
          'which interrupts the screen reader. Use aria-live="polite" or role="status" for non-urgent updates.',
      };
    }
    return { pass: false, message: 'No polite live region carries the status update' };
  });

  await assert('The status live region is exposed to assistive technology', async () => {
    const regions = after.length ? after : loadRegions;
    if (regions.length === 0) return { pass: false, message: 'No live region to evaluate' };
    const pool = regions.filter((r) => r.isSaveStatus).length ? regions.filter((r) => r.isSaveStatus) : regions;
    const visible = pool.filter((r) => !r.hidden);
    if (visible.length > 0) {
      return { pass: true, message: 'The status live region is exposed to assistive technology' };
    }
    return {
      pass: false,
      message: 'The status live region is hidden (aria-hidden="true" or display:none); screen readers will not announce it',
    };
  });

  return {};
};
