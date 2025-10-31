/* Function to dismiss the dialog by clicking a button with common dismissal names, pressing Escape, or refreshing the page */
const dismissDialog = async (page, reload = true) => {
    if (!await dialogIsOpen(page)) {
        return;
    }

    const closeButton = await page.getByRole('button', { name: /\b(close|okay|ok|dismiss|exit|cancel|submit|apply|x)\b/iu });
    if (await closeButton.count() > 0) {
        await closeButton.first().click();
    }

    if (await dialogIsOpen(page)) {
        // Try pressing escape on the dialog
        await page.getByRole('dialog').press('Escape');
    }

    if (await dialogIsOpen(page)) {
        // Fallback: press Escape on body
        await page.keyboard.press('Escape');
    }

    if (reload && await dialogIsOpen(page)) {
        // If still open, refresh the page to reset state
        await utils.reload();
    }
}

const dialogIsOpen = async (page) => {
    await page.waitForTimeout(50); // Some dialogs have animations and will wait to send focus until after a slight delay.
    // This works because page.getByRole waits for the element to appear and won't match hidden elements.
    const dialog = await page.getByRole('dialog');
    return await dialog.count() > 0;
}

/* Function to check if focus is inside the dialog
*  Checks if the activeElement is contained within the dialog or is the body (which can happen if focus is sent to the browser chrome).
*/
const focusIsInDialog = async (page) => {
    return await page.evaluate((obj) => obj.dialog.contains(document.activeElement) || document.activeElement.tagName === 'BODY', 
        { dialog: await page.getByRole('dialog').elementHandle()});
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

module.exports.run = async ({ page, assert, utils }) => {
    /* Loop through all dialog triggers, open the dialog, and assert that a dialog role is present */
    await assert("Each dialog has a dialog role", async () => {
        await utils.reload(); // Ensure clean state before starting
        const triggers = await page.locator('.trigger');
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
        const triggers = await page.locator('.trigger');
        const totalTriggers = await triggers.count();
        let totalSuccess = 0;
        for (const trigger of await triggers.all()) {
            await dismissDialog(page);
            await trigger.click(); 
            if (!await dialogIsOpen(page)) {
                throw new Error("Dialog did not open on trigger click");
            }

            await page.getByRole('dialog').press('Escape');
            if (!(await dialogIsOpen(page))) {
                totalSuccess += 1;
            }
        }
        return totalSuccess === totalTriggers;
    }, {type: 'BP'});

    await assert("Each modal dialog traps keyboard focus", async () => {
        await utils.reload(); // Ensure clean state before starting
        const triggers = await page.locator('.trigger');
        const totalTriggers = await triggers.count();
        let totalSuccess = 0;
        for (const trigger of await triggers.all()) {
            await dismissDialog(page);
            await trigger.click(); 
            if (!await dialogIsOpen(page)) {
                throw new Error("Dialog did not open on trigger click");
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
        const triggers = await page.locator('.trigger');
        const totalTriggers = await triggers.count();
        let totalSuccess = 0;
        for (const trigger of await triggers.all()) {
            await dismissDialog(page);
            await trigger.click();
            if (!await dialogIsOpen(page)) {
                throw new Error("Dialog did not open on trigger click");
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
        const triggers = await page.locator('.trigger');
        const totalTriggers = await triggers.count();
        let totalSuccess = 0;
        for (const trigger of await triggers.all()) {
            await dismissDialog(page);
            await trigger.click();
            if (!await dialogIsOpen(page)) {
                throw new Error("Dialog did not open on trigger click");
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

    await assert("Each modal dialog hides content behind it while open", async () => {
        await utils.reload(); // Ensure clean state before starting
        const triggers = await page.locator('.trigger');
        const totalTriggers = await triggers.count();
        let totalSuccess = 0;

        for (const trigger of await triggers.all()) {
            await dismissDialog(page);
            await trigger.click();
            if (!await dialogIsOpen(page)) {
                throw new Error("Dialog did not open on trigger click");
            }
            
            let isScreenReaderHidden = await trigger.evaluate(el => {
                // Use axe-core's util to determine hidden from screen reader users.
                let vEl = window.axe.utils.getNodeFromTree(el)
                return !window.axe.commons.dom.isVisibleToScreenReaders(vEl);
            });
           
            if (!isScreenReaderHidden) {
                // Trigger is still visible to screen reader users, so fail this iteration.
                continue;
            }

            totalSuccess += 1;
        }
        return totalSuccess === totalTriggers;
    });

  return {}; // assertions collected via injected assert
};

module.exports.runAxe = async ({ page, utils }) => {
    await utils.reload(); // Ensure clean state before starting

    const triggers = await page.locator('.trigger');
    let axeResult = {};

    for (const trigger of await triggers.all()) {
        await dismissDialog(page);
        await trigger.click();
        await dialogIsOpen(page);
        axeResult = utils.merge(axeResult, await utils.runAxeOnPage(page));
    }
    
    return axeResult;
};