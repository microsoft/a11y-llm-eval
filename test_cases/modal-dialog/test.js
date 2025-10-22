// New harness signature with dependency injection
module.exports.run = async ({ page, assert, utils }) => {
    /* Function to dismiss the dialog by clicking a button with common dismissal names, pressing Escape, or refreshing the page */
    const dismissDialog = async (reload = true) => {
        if (!await dialogIsOpen()) {
            return;
        }

        const closeButton = await page.getByRole('button', { name: /\b(close|okay|ok|dismiss|exit|cancel|submit|apply|x)\b/iu });
        if (await closeButton.count() > 0) {
            await closeButton.first().click();
        }

        if (await dialogIsOpen()) {
            // Try pressing escape on the dialog
            await page.getByRole('dialog').press('Escape');
        }

        if (await dialogIsOpen()) {
            // Fallback: press Escape on body
            await page.keyboard.press('Escape');
        }

        if (reload && await dialogIsOpen()) {
            // If still open, refresh the page to reset state
            await utils.reload();
        }
    }

    const dialogIsOpen = async () => {
        await page.waitForTimeout(50); // Some dialogs have animations and will wait to send focus until after a slight delay.
        // This works because page.getByRole waits for the element to appear and won't match hidden elements.
        const dialog = await page.getByRole('dialog');
        return await dialog.count() > 0;
    }

    /* Function to check if focus is inside the dialog
    *  Checks if the activeElement is contained within the dialog or is the body (which can happen if focus is sent to the browser chrome).
    */
    const focusIsInDialog = async () => {
        return await page.evaluate((obj) => obj.dialog.contains(document.activeElement) || document.activeElement.tagName === 'BODY', 
            { dialog: await page.getByRole('dialog').elementHandle()});
    }

    const tryToEscapeDialog = async (key, iterations) => {
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
            if (!await focusIsInDialog()) {
                // Focus escaped the dialog, so fail this iteration.
                return true;
            }
        }
    }

    /* Loop through all dialog triggers, open the dialog, and assert that a dialog role is present */
    await assert("Each dialog has a dialog role", async () => {
        await utils.reload(); // Ensure clean state before starting
        const triggers = await page.locator('.trigger');
        const totalTriggers = await triggers.count();
        let totalDialogs = 0;
        for (const trigger of await triggers.all()) {
            await trigger.click();
            if (await dialogIsOpen()) {
                totalDialogs += 1;
            }
            await dismissDialog();
        }
        return totalDialogs === totalTriggers;
    });

    await assert("Each dialog can be closed by escape key", async () => {
        await utils.reload(); // Ensure clean state before starting
        const triggers = await page.locator('.trigger');
        const totalTriggers = await triggers.count();
        let totalSuccess = 0;
        for (const trigger of await triggers.all()) {
            await dismissDialog();
            await trigger.click(); 
            if (!await dialogIsOpen()) {
                throw new Error("Dialog did not open on trigger click");
            }

            await page.getByRole('dialog').press('Escape');
            if (!(await dialogIsOpen())) {
                totalSuccess += 1;
            }
        }
        return totalSuccess === totalTriggers;
    }, {type: 'BP'});

    await assert("Each dialog traps keyboard focus", async () => {
        await utils.reload(); // Ensure clean state before starting
        const triggers = await page.locator('.trigger');
        const totalTriggers = await triggers.count();
        let totalSuccess = 0;
        for (const trigger of await triggers.all()) {
            await dismissDialog();
            await trigger.click(); 
            if (!await dialogIsOpen()) {
                throw new Error("Dialog did not open on trigger click");
            }

            if (await tryToEscapeDialog('Tab', 20)) {
                await dismissDialog();
                continue;
            }

            if (await tryToEscapeDialog('Shift+Tab', 20)) {
                await dismissDialog();
                continue;
            }

            totalSuccess += 1;
        }
        return totalSuccess === totalTriggers;
    });

    await assert("Each dialog takes focus when opened", async () => {
        await utils.reload(); // Ensure clean state before starting
        const triggers = await page.locator('.trigger');
        const totalTriggers = await triggers.count();
        let totalSuccess = 0;
        for (const trigger of await triggers.all()) {
            await dismissDialog();
            await trigger.click();
            if (!await dialogIsOpen()) {
                throw new Error("Dialog did not open on trigger click");
            }

            if (!(await focusIsInDialog())) {
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
            await dismissDialog();
            await trigger.click();
            if (!await dialogIsOpen()) {
                throw new Error("Dialog did not open on trigger click");
            }

            await dismissDialog(false);

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

    await assert("Each dialog hides content behind it while open", async () => {
        await utils.reload(); // Ensure clean state before starting
        const triggers = await page.locator('.trigger');
        const totalTriggers = await triggers.count();
        let totalSuccess = 0;

        for (const trigger of await triggers.all()) {
            await dismissDialog();
            await trigger.click();
            if (!await dialogIsOpen()) {
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
