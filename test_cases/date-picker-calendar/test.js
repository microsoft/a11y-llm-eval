/**
 * Date picker calendar accessibility assertions.
 *
 * Focus: the interaction-level ARIA contract for calendar day grids that a
 * static axe-core scan does not cover. The centerpiece is that a chosen day is
 * exposed as *selected* (aria-selected) rather than *pressed* (aria-pressed):
 * aria-pressed announces "button pressed", which misrepresents a calendar day,
 * whereas a day in a grid/listbox is a selection and must use aria-selected.
 * Also checks grid/listbox role semantics, programmatic selected state, and
 * keyboard navigability of the grid.
 *
 * Grounded in the "aria-pressed-in-selection-context" and
 * "option-missing-aria-selected" anti-patterns (WAI-ARIA 1.2; WCAG SC 4.1.2;
 * Class III — Widget Role Contract Violation).
 */

const normalizeText = (value) => (value || '').toString().replace(/[\s ]+/g, ' ').trim();

const DAY_NUMBER = /^([1-9]|[12]\d|3[01])$/;
const SELECTION_CELL_ROLES = ['gridcell', 'option', 'row'];
const SELECTION_CONTAINER_ROLES = ['grid', 'listbox', 'table'];

// Tag and collect candidate "day cells" inside the date picker so later
// assertions can re-locate a specific cell via [data-arr-day-index].
const collectDayCells = async (page) =>
    page.evaluate(() => {
        const scopeEl = document.querySelector('.date-picker') || document.body;
        const candidates = new Set();

        // Explicit selection / grid semantics.
        scopeEl
            .querySelectorAll('[role="gridcell"], [role="option"], [aria-selected], [aria-pressed]')
            .forEach((el) => candidates.add(el));

        // Clickable elements whose label is a day-of-month number (1–31).
        scopeEl.querySelectorAll('button, td, [tabindex], [role="button"]').forEach((el) => {
            const text = (el.textContent || '').trim();
            if (/^([1-9]|[12]\d|3[01])$/.test(text)) candidates.add(el);
        });

        return [...candidates].map((el, i) => {
            el.setAttribute('data-arr-day-index', String(i));
            let name = el.getAttribute('aria-label') || '';
            const labelledBy = el.getAttribute('aria-labelledby');
            if (!name && labelledBy) {
                name = labelledBy
                    .split(/\s+/)
                    .map((id) => {
                        const node = document.getElementById(id);
                        return node ? node.textContent : '';
                    })
                    .join(' ');
            }
            if (!name) name = el.textContent || '';

            const container = el.closest('[role="grid"], [role="listbox"], [role="table"], table');
            return {
                index: i,
                name: name.replace(/[\s ]+/g, ' ').trim(),
                role: el.getAttribute('role') || el.tagName.toLowerCase(),
                ariaSelected: el.getAttribute('aria-selected'),
                ariaPressed: el.getAttribute('aria-pressed'),
                ariaCurrent: el.getAttribute('aria-current'),
                containerRole: container ? container.getAttribute('role') || container.tagName.toLowerCase() : null,
                tag: el.tagName.toLowerCase(),
                tabindex: el.getAttribute('tabindex'),
            };
        });
    });

// Best effort: open the calendar by clicking a non-submit trigger in the picker.
const openCalendar = async (page) => {
    const triggers = page.locator('.date-picker button, .date-picker [role="button"], .date-picker input');
    const count = await triggers.count().catch(() => 0);
    for (let i = 0; i < count; i += 1) {
        const el = triggers.nth(i);
        const text = normalizeText(await el.innerText().catch(() => ''));
        const type = (await el.getAttribute('type').catch(() => '')) || '';
        if (/submit/i.test(text) || type === 'submit') continue;
        await el.click().catch(() => {});
        await page.waitForTimeout(50);
        const cells = await collectDayCells(page);
        if (cells.length > 0) return cells;
    }
    return collectDayCells(page);
};

module.exports.run = async ({ page, assert, utils }) => {
    const reload = async () => {
        if (utils && typeof utils.reload === 'function') {
            await utils.reload();
        } else {
            await page.reload();
        }
        await page.waitForTimeout(50);
    };

    let dayCells = await openCalendar(page);

    await assert('Calendar day grid is present and openable', async () => {
        if (dayCells.length === 0) {
            return { pass: false, message: 'No calendar day cells were found after opening the date picker' };
        }
        return { pass: true, message: `Found ${dayCells.length} day cells` };
    });

    await assert('Each calendar day has an accessible name', async () => {
        if (dayCells.length === 0) return { pass: false, message: 'No day cells to evaluate' };
        const unnamed = dayCells.filter((cell) => !normalizeText(cell.name));
        if (unnamed.length === 0) return { pass: true, message: 'All day cells have accessible names' };
        return { pass: false, message: `${unnamed.length} day cell(s) have no accessible name` };
    });

    await assert('Day cells expose grid or listbox selection semantics', async () => {
        if (dayCells.length === 0) return { pass: false, message: 'No day cells to evaluate' };
        const ok = dayCells.filter(
            (cell) =>
                SELECTION_CELL_ROLES.includes(cell.role) ||
                (cell.containerRole && SELECTION_CONTAINER_ROLES.includes(cell.containerRole)),
        );
        if (ok.length >= Math.ceil(dayCells.length / 2)) {
            return { pass: true, message: 'Day cells sit within a grid/listbox with selection roles' };
        }
        return {
            pass: false,
            message:
                'Day cells are not exposed as gridcell/option within a grid or listbox; ' +
                'assistive technology cannot interpret them as selectable days',
        };
    });

    // Centerpiece: aria-selected (selection) vs aria-pressed (toggle button).
    await assert('Selection uses aria-selected, not aria-pressed', async () => {
        if (dayCells.length === 0) return { pass: false, message: 'No day cells to evaluate' };
        const pressed = dayCells.filter((cell) => cell.ariaPressed !== null && cell.ariaPressed !== undefined);
        if (pressed.length > 0) {
            return {
                pass: false,
                message:
                    `${pressed.length} day cell(s) use aria-pressed. A calendar day is a selection within a grid, ` +
                    'so it must use aria-selected — aria-pressed makes screen readers announce "button pressed" ' +
                    'instead of "selected".',
            };
        }
        const hasSelected = dayCells.some((cell) => cell.ariaSelected !== null && cell.ariaSelected !== undefined);
        if (!hasSelected) {
            return {
                pass: false,
                message: 'No day cell exposes aria-selected; selection state is not communicated to assistive technology',
            };
        }
        return { pass: true, message: 'Day cells communicate selection with aria-selected and avoid aria-pressed' };
    });

    await assert('Exactly one day is marked selected after a day is chosen', async () => {
        let selected = dayCells.filter((cell) => String(cell.ariaSelected) === 'true');
        if (selected.length !== 1) {
            const target =
                dayCells.find(
                    (cell) =>
                        DAY_NUMBER.test(normalizeText(cell.name)) ||
                        cell.role === 'gridcell' ||
                        cell.role === 'option',
                ) || dayCells[0];
            if (target) {
                await page.locator(`[data-arr-day-index="${target.index}"]`).click().catch(() => {});
                await page.waitForTimeout(50);
                let after = await collectDayCells(page);
                if (after.length === 0) {
                    await openCalendar(page);
                    after = await collectDayCells(page);
                }
                dayCells = after;
                selected = dayCells.filter((cell) => String(cell.ariaSelected) === 'true');
            }
        }
        if (selected.length === 1) {
            return { pass: true, message: 'Exactly one day is programmatically marked selected' };
        }
        return { pass: false, message: `Expected exactly one day with aria-selected="true"; found ${selected.length}` };
    });

    await assert('Arrow keys move focus within the day grid', async () => {
        await reload();
        const cells = await openCalendar(page);
        if (cells.length < 2) {
            return { pass: false, message: 'Not enough day cells to test keyboard navigation' };
        }
        const start = cells.find((cell) => cell.tabindex !== null) || cells[0];
        const locator = page.locator(`[data-arr-day-index="${start.index}"]`);
        await locator.focus().catch(() => {});
        const before = await page.evaluate(
            () => document.activeElement && document.activeElement.getAttribute('data-arr-day-index'),
        );
        await locator.press('ArrowRight').catch(() => {});
        await page.waitForTimeout(30);
        let after = await page.evaluate(
            () => document.activeElement && document.activeElement.getAttribute('data-arr-day-index'),
        );
        if (after === before) {
            await page.keyboard.press('ArrowDown').catch(() => {});
            await page.waitForTimeout(30);
            after = await page.evaluate(
                () => document.activeElement && document.activeElement.getAttribute('data-arr-day-index'),
            );
        }
        if (after && after !== before) {
            return { pass: true, message: 'Arrow keys move focus between day cells' };
        }
        return {
            pass: false,
            message: 'Arrow keys did not move focus within the day grid; keyboard users cannot navigate the calendar',
        };
    });

    return {};
};
