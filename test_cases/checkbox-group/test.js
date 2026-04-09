/**
 * Checkbox group accessibility test assertions.
 * Supports native checkboxes and custom ARIA checkbox groups.
 */

module.exports.run = async ({ page, assert, utils }) => {
    const discovery = await utils.testFormControls.discoverCheckboxes(page);

    await assert("Each checkbox has a valid role", async () => {
        const checkboxes = discovery.inputs;

        if (checkboxes.length === 0) {
            return { pass: false, message: 'No checkboxes found in scope' };
        }

        let invalidCount = 0;
        for (const checkbox of checkboxes) {
            const hasValidRole = await checkbox.locator.evaluate((el) => {
                const explicitRole = (el.getAttribute('role') || '').trim().toLowerCase();
                const isNativeCheckbox = el.matches('input[type="checkbox"]');

                if (isNativeCheckbox) {
                    return explicitRole === '' || explicitRole === 'checkbox';
                }

                return explicitRole === 'checkbox';
            });

            if (!hasValidRole) {
                invalidCount += 1;
            }
        }

        if (invalidCount === 0) {
            return { pass: true, message: 'All checkboxes expose valid checkbox roles' };
        }

        return { pass: false, message: `${invalidCount} checkbox option(s) do not expose a valid checkbox role` };
    });

    await assert("Each checkbox has an accessible name", async () => {
        const checkboxes = discovery.inputs;

        if (checkboxes.length === 0) {
            return { pass: false, message: 'No checkboxes found in scope' };
        }

        const unnamedCount = checkboxes.filter((checkbox) => !checkbox.name).length;
        if (unnamedCount === 0) {
            return { pass: true, message: 'All checkboxes have accessible names' };
        }

        return { pass: false, message: `${unnamedCount} checkbox option(s) are missing accessible names` };
    });

    await assert("Visible label is included in accessible name", async () => {
        const results = await utils.testFormControls.testLabelInName(page, discovery);
        return { status: results.status(), message: results.getMessage() };
    });

    await assert("Visual labels are defined and persistent", async () => {
        const results = await utils.testFormControls.testEachInputHasPersistentVisualLabel(page, discovery);
        return { status: results.status(), message: results.getMessage() };
    });

    await assert("Helper text is programmatically associated", async () => {
        const results = await utils.testFormControls.testHelperTextAssociated(page, discovery);
        return { status: results.status(), message: results.getMessage() };
    });

    await assert("Required fields are indicated visually", async () => {
        const results = await utils.testFormControls.testRequiredFieldsIndicatedVisually(page, discovery);
        return { status: results.status(), message: results.getMessage() };
    });

    await assert("Required fields are indicated programmatically", async () => {
        const results = await utils.testFormControls.testRequiredFieldsIndicatedProgrammatically(page, discovery);
        return { status: results.status(), message: results.getMessage() };
    });

    await assert("Each checkbox group has an accessible label", async () => {
        const groups = await utils.testFormControls.discoverCheckboxGroups(page, discovery);

        if (groups.length === 0) {
            return { pass: false, message: 'No checkbox groups found in scope' };
        }

        const unlabeledGroups = groups.filter((group) => !group.groupLabel);
        if (unlabeledGroups.length === 0) {
            return { pass: true, message: 'All checkbox groups have accessible labels' };
        }

        return { pass: false, message: `${unlabeledGroups.length} checkbox group(s) are missing accessible labels` };
    });

    await assert("Each checkbox group has a valid role", async () => {
        const groups = await utils.testFormControls.discoverCheckboxGroups(page, discovery);

        if (groups.length === 0) {
            return { pass: false, message: 'No checkbox groups found in scope' };
        }

        const invalidGroups = groups.filter((group) => group.groupKind !== 'fieldset' && group.groupKind !== 'group');
        if (invalidGroups.length === 0) {
            return { pass: true, message: 'All checkbox groups expose valid group roles' };
        }

        return { pass: false, message: `${invalidGroups.length} checkbox group(s) do not expose a valid group role` };
    });

    await assert("Each checkbox is in the tab order", async () => {
        const checkboxes = discovery.inputs;

        if (checkboxes.length === 0) {
            return { pass: false, message: 'No checkboxes found in scope' };
        }

        const outOfTabOrder = checkboxes.filter((checkbox) => checkbox.visible && !checkbox.disabled && checkbox.tabIndex < 0);

        if (outOfTabOrder.length === 0) {
            return { pass: true, message: 'Each interactive checkbox is in the tab order' };
        }

        return { pass: false, message: `${outOfTabOrder.length} checkbox option(s) are not in the tab order` };
    });

    await assert("Space toggles checkbox state of each checkbox", async () => {
        await utils.reload();
        let currentDiscovery = await utils.testFormControls.discoverCheckboxes(page);

        if (currentDiscovery.inputs.length === 0) {
            return { pass: false, message: 'No checkboxes found in scope' };
        }

        let applicableCheckboxes = 0;
        let passingCheckboxes = 0;

        for (let checkboxIndex = 0; checkboxIndex < currentDiscovery.inputs.length; checkboxIndex += 1) {
            await utils.reload();
            currentDiscovery = await utils.testFormControls.discoverCheckboxes(page);
            const checkbox = currentDiscovery.inputs[checkboxIndex];
            if (!checkbox || !checkbox.visible || checkbox.disabled) {
                continue;
            }

            applicableCheckboxes += 1;

            const locator = page.locator('input[type="checkbox"], [role="checkbox"]').nth(checkbox.domIndex);
            await locator.focus();
            const before = checkbox.checked;

            await locator.press(' ');
            await page.waitForTimeout(30);

            const updatedDiscovery = await utils.testFormControls.discoverCheckboxes(page);
            const after = updatedDiscovery.inputs[checkboxIndex] ? updatedDiscovery.inputs[checkboxIndex].checked : before;

            if (after !== before) {
                passingCheckboxes += 1;
            }
        }

        if (applicableCheckboxes === 0) {
            return { pass: false, message: 'No interactive checkboxes were available for Space-key testing' };
        }

        if (passingCheckboxes === applicableCheckboxes) {
            return { pass: true, message: 'Space toggles each checkbox state' };
        }

        return { pass: false, message: `${applicableCheckboxes - passingCheckboxes} checkbox option(s) did not toggle state on Space` };
    });

    await assert("ARIA attributes match native checkbox attributes if used", async () => {
        const checkboxes = discovery.inputs;

        if (checkboxes.length === 0) {
            return { pass: false, message: 'No checkboxes found in scope' };
        }

        const invalidCheckboxes = checkboxes.filter((checkbox) => checkbox.hasNativeAriaStateMismatch);
        if (invalidCheckboxes.length === 0) {
            return { pass: true, message: 'ARIA state is consistent with native checkbox state' };
        }

        const mismatchCount = invalidCheckboxes.reduce((total, checkbox) => total + (checkbox.nativeAriaStateMismatchCount || 0), 0);
        return {
            pass: false,
            message: `${invalidCheckboxes.length} checkbox option(s) have ${mismatchCount} conflicting native and ARIA state value(s)`,
        };
    });

    await assert("Checked state is programmatically exposed", async () => {
        const checkboxes = discovery.inputs;

        if (checkboxes.length === 0) {
            return { pass: false, message: 'No checkboxes found in scope' };
        }

        const invalidCount = checkboxes.filter((checkbox) => !checkbox.checkedStateDefined || checkbox.checkedStateMismatch).length;
        if (invalidCount === 0) {
            return { pass: true, message: 'All checkboxes expose checked state programmatically' };
        }

        return { pass: false, message: `${invalidCount} checkbox option(s) do not expose checked state programmatically without contradiction` };
    });

    return {};
};