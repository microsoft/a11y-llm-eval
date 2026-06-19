/**
 * Listbox picker accessibility assertions.
 *
 * Custom dropdown "picker" menus (font/style selectors, etc.) frequently expose
 * no ARIA semantics: the popup is not a listbox, items are not options, the
 * selected item has no aria-selected, the trigger does not announce open/closed,
 * and there is no keyboard support. axe-core does not flag a div-based dropdown
 * that "looks" interactive, so these are checked here.
 *
 * Grounded in the "haspopup-missing-aria-expanded", "listbox-missing-options",
 * and "option-missing-aria-selected" anti-patterns (WAI-ARIA 1.2;
 * WCAG SC 4.1.2; Class III — Widget Role Contract Violation).
 */

const normalizeText = (value) => (value || '').toString().replace(/[\s ]+/g, ' ').trim();

const scopeSelector = '.style-picker';

// Click a non-submit trigger to open the menu; returns nothing.
const openPicker = async (page) => {
  const triggers = page.locator(scopeSelector + ' button, ' + scopeSelector + ' [role="button"], ' + scopeSelector + ' [aria-haspopup]');
  const count = await triggers.count().catch(() => 0);
  for (let i = 0; i < count; i += 1) {
    const el = triggers.nth(i);
    const text = normalizeText(await el.innerText().catch(() => ''));
    const type = (await el.getAttribute('type').catch(() => '')) || '';
    if (/submit/i.test(text) || type === 'submit') continue;
    await el.click().catch(() => {});
    await page.waitForTimeout(50);
    break;
  }
};

// Collect option-like items inside the picker: role="option" first, else the
// menu's clickable children. Tags each with [data-arr-opt-index].
const collectOptions = async (page) =>
  page.evaluate((sel) => {
    const scope = document.querySelector(sel) || document.body;
    let els = Array.from(scope.querySelectorAll('[role="option"]'));
    if (els.length === 0) {
      // Fallback: clickable menu items (so we can still report missing roles).
      const menu = scope.querySelector('[role="listbox"], [role="menu"], ul, .menu, .options, .dropdown') || scope;
      els = Array.from(menu.querySelectorAll('li, [role="menuitem"], button, a, [tabindex]')).filter(
        (el) => (el.textContent || '').trim().length > 0,
      );
    }
    return els.map((el, i) => {
      el.setAttribute('data-arr-opt-index', String(i));
      let name = el.getAttribute('aria-label') || '';
      if (!name) name = el.textContent || '';
      const container = el.closest('[role="listbox"]');
      return {
        index: i,
        name: name.replace(/[\s ]+/g, ' ').trim(),
        role: el.getAttribute('role') || el.tagName.toLowerCase(),
        ariaSelected: el.getAttribute('aria-selected'),
        inListbox: Boolean(container),
        tabindex: el.getAttribute('tabindex'),
      };
    });
  }, scopeSelector);

const getTrigger = async (page) =>
  page.evaluate((sel) => {
    const scope = document.querySelector(sel) || document.body;
    const buttons = Array.from(scope.querySelectorAll('button, [role="button"], [aria-haspopup]'));
    const trigger = buttons.find((b) => (b.getAttribute('type') || '') !== 'submit' && !/submit/i.test(b.textContent || ''));
    if (!trigger) return null;
    return {
      ariaHaspopup: trigger.getAttribute('aria-haspopup'),
      ariaExpanded: trigger.getAttribute('aria-expanded'),
    };
  }, scopeSelector);

module.exports.run = async ({ page, assert, utils }) => {
  const reload = async () => {
    if (utils && typeof utils.reload === 'function') await utils.reload();
    else await page.reload();
    await page.waitForTimeout(50);
  };

  await openPicker(page);

  await assert('Picker trigger exposes popup state (aria-haspopup and aria-expanded)', async () => {
    const t = await getTrigger(page);
    if (!t) return { pass: false, message: 'No picker trigger button found' };
    if (!t.ariaHaspopup) {
      return { pass: false, message: 'Trigger has no aria-haspopup; assistive technology cannot announce that it opens a popup' };
    }
    if (t.ariaExpanded === null || t.ariaExpanded === undefined) {
      return { pass: false, message: 'Trigger has aria-haspopup but no aria-expanded; AT cannot announce whether the popup is open or closed' };
    }
    return { pass: true, message: 'Trigger exposes aria-haspopup and aria-expanded' };
  });

  await assert('Open menu uses role=listbox with role=option children', async () => {
    const hasListbox = await page.locator(scopeSelector + ' [role="listbox"]').count().catch(() => 0);
    const options = await collectOptions(page);
    const realOptions = options.filter((o) => o.role === 'option' && o.inListbox);
    if (hasListbox > 0 && realOptions.length > 0) {
      return { pass: true, message: `Listbox with ${realOptions.length} option children` };
    }
    return {
      pass: false,
      message: 'Popup is not exposed as role="listbox" with role="option" children; screen readers cannot present it as a selectable list',
    };
  });

  await assert('Each option has an accessible name', async () => {
    const options = await collectOptions(page);
    if (options.length === 0) return { pass: false, message: 'No options found in the menu' };
    const unnamed = options.filter((o) => !normalizeText(o.name));
    if (unnamed.length === 0) return { pass: true, message: 'All options have accessible names' };
    return { pass: false, message: `${unnamed.length} option(s) have no accessible name` };
  });

  await assert('Options expose selection state with aria-selected', async () => {
    const options = await collectOptions(page);
    if (options.length === 0) return { pass: false, message: 'No options found in the menu' };
    const withSelected = options.filter((o) => o.ariaSelected !== null && o.ariaSelected !== undefined);
    if (withSelected.length === 0) {
      return { pass: false, message: 'No option exposes aria-selected; AT cannot announce which option is current' };
    }
    const selectedTrue = options.filter((o) => String(o.ariaSelected) === 'true');
    if (selectedTrue.length !== 1) {
      return { pass: false, message: `Expected exactly one option with aria-selected="true"; found ${selectedTrue.length}` };
    }
    return { pass: true, message: 'Options expose aria-selected with exactly one selected' };
  });

  await assert('Arrow keys move the active option', async () => {
    await reload();
    await openPicker(page);
    const options = await collectOptions(page);
    if (options.length < 2) return { pass: false, message: 'Not enough options to test keyboard navigation' };

    // The "active option" is whichever the widget tracks: the focused option
    // (roving tabindex) or the listbox's aria-activedescendant.
    const readActive = () =>
      page.evaluate(() => {
        const ae = document.activeElement;
        if (!ae || !ae.getAttribute) return null;
        const adesc = ae.getAttribute('aria-activedescendant');
        if (adesc) return 'ad:' + adesc;
        const oi = ae.getAttribute('data-arr-opt-index');
        return oi !== null && oi !== undefined ? 'oi:' + oi : null;
      });

    let before = await readActive();
    if (!before) {
      // Nothing focused on open — focus the first option to start.
      await page.locator('[data-arr-opt-index="0"]').focus().catch(() => {});
      before = await readActive();
    }
    await page.keyboard.press('ArrowDown').catch(() => {});
    await page.waitForTimeout(30);
    const after = await readActive();
    if (after && after !== before) {
      return { pass: true, message: 'Arrow keys move the active option' };
    }
    return { pass: false, message: 'Arrow keys did not move the active option; keyboard users cannot navigate the menu' };
  });

  await assert('Escape closes the listbox', async () => {
    await reload();
    await openPicker(page);
    const t1 = await getTrigger(page);
    const openBefore = t1 && String(t1.ariaExpanded) === 'true';
    const visibleBefore = (await page.locator(scopeSelector + ' [role="listbox"]:visible').count().catch(() => 0)) > 0;
    if (!openBefore && !visibleBefore) {
      return { pass: false, message: 'Menu did not appear open after activating the trigger, so close-on-Escape cannot be verified' };
    }
    await page.keyboard.press('Escape').catch(() => {});
    await page.waitForTimeout(30);
    const t2 = await getTrigger(page);
    const expandedAfter = t2 ? String(t2.ariaExpanded) === 'true' : false;
    const visibleAfter = (await page.locator(scopeSelector + ' [role="listbox"]:visible').count().catch(() => 0)) > 0;
    if (!expandedAfter && !visibleAfter) {
      return { pass: true, message: 'Escape closes the listbox' };
    }
    return { pass: false, message: 'Escape did not close the listbox (aria-expanded stayed true / listbox stayed visible)' };
  });

  return {};
};
