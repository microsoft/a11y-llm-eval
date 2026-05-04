const { isExposedToAccessibilityTree } = require('../../node_runner/helpers/get-accessibility-tree');

/* Function to dismiss the dialog by clicking a button with common dismissal names, pressing Escape, or refreshing the page */
const dismissDialog = async (page, reload = true) => {
    if (!await dialogIsOpen(page)) {
        return;
    }

    if (await dialogIsOpen(page)) {
        // Try pressing escape on the dialog
        await page.getByRole('dialog').or(page.getByRole('alertdialog')).press('Escape');
    }

    if (await dialogIsOpen(page)) {
        // Fallback: press Escape on body
        await page.keyboard.press('Escape');
    }

    if (await dialogIsOpen(page)) {
        // Fallback: by clicking outside the dialog
        await page.locator('body').click({position: {x: 0, y: 0}});
    }

    const closeButton = await page.getByRole('button', { name: /\b(close|okay|ok|dismiss|exit|cancel|submit|apply|x)\b/iu });
    if (await dialogIsOpen(page) && await closeButton.count() > 0) {
        await closeButton.first().click();
    }

    const closeControl = await page.getByRole('*', { name: /\b(close|okay|ok|dismiss|exit|cancel|submit|apply|x)\b/iu });
    if (await dialogIsOpen(page) && await closeControl.count() > 0) {
        await closeControl.first().click();
    }

    if (reload && await dialogIsOpen(page)) {
        // If still open, refresh the page to reset state
        await utils.reload();
    }
}

const waitForAnimationEnd = async (locator) => {
  return locator.evaluate((element) => 
    Promise.all(
        element
            .getAnimations({ subtree: true })
            .map((animation) => animation.finished)
        )
    )
}

const dialogIsOpen = async (page) => {
    // Some JS frameworks delay the addition/removal of the dialog to the DOM until after animations complete.
    await page.waitForTimeout(50);

    // Now wait for any animations to end
    const body = await page.locator('body');
    await waitForAnimationEnd(body);

    // Now, check for dialog presence and visibility.
    // Some implementations keep the dialog in the DOM but hide it with opacity/pointer-events/hidden attr.
    const dialog = page.getByRole('dialog').or(page.getByRole('alertdialog'));
    if (await dialog.count() === 0) return false;

    // Playwright's isVisible() doesn't account for opacity:0, so check it ourselves.
    return await dialog.first().evaluate(el => {
        if (el.hidden) return false;
        const s = window.getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden') return false;
        if (parseFloat(s.opacity) === 0) return false;
        return true;
    });
}

/* Function to check if focus is inside the dialog
*  Checks if the activeElement is contained within the dialog or is the body (which can happen if focus is sent to the browser chrome).
*/
const focusIsInDialog = async (page) => {
    return await page.evaluate((obj) => obj.dialog.contains(document.activeElement) || document.activeElement.tagName === 'BODY', 
        { dialog: await page.getByRole('dialog').or(page.getByRole('alertdialog')).elementHandle()});
}

const tryToEscapeDialog = async (page, key, iterations) => {
    // Tab forward many times to see if we can escape the dialog.
    let foundElements = [];
    for (let i = 0; i < iterations; i++) {
        await page.keyboard.press(key);
        let focusedElement = await page.evaluate(() => document.activeElement);
        if (foundElements.includes(focusedElement)) {
            // We have cycled through all focusable elements, so stop.
            return false;
        }
        foundElements.push(focusedElement);
        if (!await focusIsInDialog(page)) {
            // Focus escaped the dialog, so fail this iteration.
            return true;
        }
    }
}

const getTriggers = async (page) => {
    return await page.locator('.trigger').filter({ visible: true });
}

module.exports.run = async ({ page, assert, utils }) => {
    /* Loop through all dialog triggers, open the dialog, and assert that a dialog role is present */
    await assert("Each dialog has a dialog role", async () => {
        await utils.reload(); // Ensure clean state before starting
        await dismissDialog(page, false); // Ensure no dialog is open
        const triggers = await getTriggers(page);
        const totalTriggers = await triggers.count();
        let totalDialogs = 0;
        for (const trigger of await triggers.all()) {
            await trigger.click();
            if (await dialogIsOpen(page)) {
                totalDialogs += 1;
            }
            await dismissDialog(page);
        }
        return totalDialogs === totalTriggers;
    });

    await assert("Each dialog can be closed by escape key", async () => {
        await utils.reload(); // Ensure clean state before starting
        await dismissDialog(page, false); // Ensure no dialog is open
        const triggers = await getTriggers(page);
        const totalTriggers = await triggers.count();
        let totalSuccess = 0;
        for (const trigger of await triggers.all()) {
            await dismissDialog(page);
            await trigger.click(); 
            if (!await dialogIsOpen(page)) {
                throw new Error("Unable to test because no dialog was found");
            }

            await page.getByRole('dialog').or(page.getByRole('alertdialog')).press('Escape');
            if (!(await dialogIsOpen(page))) {
                totalSuccess += 1;
            }
        }
        return totalSuccess === totalTriggers;
    }, {type: 'BP'});

    await assert("Each modal dialog traps keyboard focus", async () => {
        await utils.reload(); // Ensure clean state before starting
        await dismissDialog(page, false); // Ensure no dialog is open
        const triggers = await getTriggers(page);
        const totalTriggers = await triggers.count();
        let totalSuccess = 0;
        for (const trigger of await triggers.all()) {
            await dismissDialog(page);
            await trigger.click(); 
            if (!await dialogIsOpen(page)) {
                throw new Error("Unable to test because no dialog was found");
            }

            if (await tryToEscapeDialog(page, 'Tab', 20)) {
                await dismissDialog(page);
                continue;
            }

            if (await tryToEscapeDialog(page, 'Shift+Tab', 20)) {
                await dismissDialog(page);
                continue;
            }

            totalSuccess += 1;
        }
        return totalSuccess === totalTriggers;
    });

    await assert("Each modal dialog takes focus when opened", async () => {
        await utils.reload(); // Ensure clean state before starting
        await dismissDialog(page, false); // Ensure no dialog is open
        const triggers = await getTriggers(page);
        const totalTriggers = await triggers.count();
        let totalSuccess = 0;
        for (const trigger of await triggers.all()) {
            await dismissDialog(page);
            await trigger.click();
            if (!await dialogIsOpen(page)) {
                throw new Error("Unable to test because no dialog was found");
            }

            if (!(await focusIsInDialog(page))) {
                // Focus is not in the dialog, so fail this iteration.
                continue;
            }

            const bodyIsFocused = await page.evaluate(() => document.activeElement.tagName === 'BODY');
            if (bodyIsFocused) {
                // Focus is on body, meaning that focus was lost, so fail this iteration.
                // focusIsInDialog would have returned true if focus was on the Body element.
                continue;
            }

            totalSuccess += 1;
        }
        return totalSuccess === totalTriggers;
    });

    await assert("Focus is not lost when each dialog closes", async () => {
        await utils.reload(); // Ensure clean state before starting
        await dismissDialog(page, false); // Ensure no dialog is open
        const triggers = await getTriggers(page);
        const totalTriggers = await triggers.count();
        let totalSuccess = 0;
        for (const trigger of await triggers.all()) {
            await dismissDialog(page);
            await trigger.click();
            if (!await dialogIsOpen(page)) {
                throw new Error("Unable to test because no dialog was found");
            }

            await dismissDialog(page, false);

            const bodyIsFocused = await page.evaluate(() => document.activeElement.tagName === 'BODY');
            if (bodyIsFocused) {
                // Focus is on body, meaning that focus was lost, so fail this iteration.
                // focusIsInDialog would have returned true if focus was on the Body element.
                // Note: this does not cover the scenario where the modal dialog triggers automatically on page load before the user can interact with the page. In this situation, focus should return to the body.
                continue;
            }

            totalSuccess += 1;
        }
        return totalSuccess === totalTriggers;
    });

    await assert("Closed dialogs are not exposed to assistive technology", async () => {
        await utils.reload(); // Ensure clean state before starting
        await dismissDialog(page, false); // Ensure no dialog is open

        // Before any trigger is clicked, check that no dialog role appears in the
        // accessibility tree. getByRole queries the accessibility tree, so if a
        // dialog is found, it's exposed to assistive technology regardless of
        // visual hiding (e.g. opacity:0).
        const exposedDialogs = page.getByRole('dialog').or(page.getByRole('alertdialog'));
        const exposedCount = await exposedDialogs.count();

        if (exposedCount === 0) {
            return true;
        }

        let failureReasons = [];
        for (let i = 0; i < exposedCount; i++) {
            const dialog = exposedDialogs.nth(i);
            const label = await dialog.evaluate(el => {
                return el.getAttribute('aria-label')
                    || (el.getAttribute('aria-labelledby') && document.getElementById(el.getAttribute('aria-labelledby'))?.textContent?.trim())
                    || '';
            });
            const displayLabel = label || `dialog ${i + 1}`;
            failureReasons.push(
                `Dialog "${displayLabel}" is exposed in the accessibility tree when closed. ` +
                `Use the hidden attribute, display:none, or remove the dialog from the DOM when not open. ` +
                `opacity:0 alone does not hide content from screen readers or the tab order.`
            );
        }

        return { pass: false, message: failureReasons.join(' ') };
    });

    await assert("Each modal dialog hides content behind it while open", async () => {
        await utils.reload(); // Ensure clean state before starting
        await dismissDialog(page, false); // Ensure no dialog is open
        const triggers = await getTriggers(page);
        const totalTriggers = await triggers.count();
        let totalSuccess = 0;

        let failureReasons = [];
        for (const trigger of await triggers.all()) {
            await dismissDialog(page);
            await trigger.click();
            if (!await dialogIsOpen(page)) {
                throw new Error("Unable to test because no dialog was found");
            }

            // Determine if native modal dialog is opened, which always hides background content.
            let isNativeModal = await page.evaluate(() => {
                return !!document.querySelector(':modal')
            });

            if (!isNativeModal) {
                // Check the accessibility tree directly — if the trigger is still
                // exposed, background content hasn't been properly hidden.
                let isTriggerExposed = await isExposedToAccessibilityTree(trigger);

                if (isTriggerExposed) {
                    // Trigger is still visible to screen reader users, so fail this iteration.
                    // Detect partial attempts so the message can explain what's missing.
                    const { hasAriaModal, hasAriaHidden } = await page.evaluate(() => {
                        const dialogs = document.querySelectorAll('[role="dialog"], [role="alertdialog"]');
                        let hasAriaModal = false;
                        for (const d of dialogs) {
                            if (d.getAttribute('aria-modal') === 'true') hasAriaModal = true;
                        }
                        // Check for aria-hidden on elements outside the dialog(s).
                        let hasAriaHidden = false;
                        document.querySelectorAll('[aria-hidden="true"]').forEach(el => {
                            for (const d of dialogs) {
                                if (d.contains(el)) return;
                            }
                            hasAriaHidden = true;
                        });
                        return { hasAriaModal, hasAriaHidden };
                    });

                    const triggerText = await trigger.textContent();
                    let reason = `Background content (trigger "${triggerText.trim()}") is still exposed to assistive technology while the dialog is open.`;
                    if (hasAriaModal && !hasAriaHidden) {
                        reason += ` Found aria-modal="true" on the dialog, but this alone does not remove background content from the focus order or accessibility tree.`;
                    } else if (hasAriaHidden && !hasAriaModal) {
                        reason += ` Found aria-hidden="true" on background content, but this alone does not remove it from the focus order.`;
                    } else if (hasAriaModal && hasAriaHidden) {
                        reason += ` Found aria-modal="true" and aria-hidden="true", but these alone do not remove background content from the focus order.`;
                    }
                    reason += ` Use the inert attribute on background content or a native <dialog> element with showModal().`;
                    failureReasons.push(reason);
                    continue;
                }
            }
            
            totalSuccess += 1;
        }
        if (totalSuccess === totalTriggers) return true;
        return { pass: false, message: failureReasons.join(' ') };
    });

  return {}; // assertions collected via injected assert
};

module.exports.runAxe = async ({ page, utils }) => {
    await utils.reload(); // Ensure clean state before starting
    await dismissDialog(page, false); // Ensure no dialog is open

    const triggers = await getTriggers(page);
    let axeResult = {};

    for (const trigger of await triggers.all()) {
        await dismissDialog(page);
        await trigger.click();
        await dialogIsOpen(page);
        axeResult = utils.merge(axeResult, await utils.runAxeOnPage(page));
    }
    
    return axeResult;
};