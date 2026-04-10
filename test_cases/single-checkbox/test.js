/**
 * Single checkbox accessibility test assertions.
 * Supports native checkboxes and custom ARIA checkboxes.
 */

const normalizeText = (value) => (value || '').toString().replace(/[\s\u00A0]+/g, ' ').trim();
const summarizeList = (items, maxItems = 4) => {
    const filtered = items.filter(Boolean);
    if (filtered.length <= maxItems) {
        return filtered.join(', ');
    }
    return `${filtered.slice(0, maxItems).join(', ')}, and ${filtered.length - maxItems} more`;
};
const describeCheckbox = (checkbox, index) => {
    const label = normalizeText((checkbox.visualLabel && checkbox.visualLabel.text) || checkbox.name);
    return label ? `checkbox "${label}"` : `checkbox ${index + 1}`;
};

module.exports.run = async ({ page, assert, utils }) => {
    const discovery = await utils.testFormControls.discoverCheckboxes(page);

    await assert("Each checkbox has a valid role", async () => {
        const checkboxes = discovery.inputs;

        if (checkboxes.length === 0) {
            return { pass: false, message: 'No checkboxes found in scope' };
        }

        const invalidCheckboxes = [];
        for (const [index, checkbox] of checkboxes.entries()) {
            const hasValidRole = await checkbox.locator.evaluate((el) => {
                const explicitRole = (el.getAttribute('role') || '').trim().toLowerCase();
                const isNativeCheckbox = el.matches('input[type="checkbox"]');

                if (isNativeCheckbox) {
                    return explicitRole === '' || explicitRole === 'checkbox';
                }

                return explicitRole === 'checkbox';
            });

            if (!hasValidRole) {
                invalidCheckboxes.push(describeCheckbox(checkbox, index));
            }
        }

        if (invalidCheckboxes.length === 0) {
            return { pass: true, message: 'All checkboxes expose valid checkbox roles' };
        }

        return { pass: false, message: `Invalid checkbox role on ${summarizeList(invalidCheckboxes)}` };
    });

    await assert("Each checkbox has an accessible name", async () => {
        const checkboxes = discovery.inputs;

        if (checkboxes.length === 0) {
            return { pass: false, message: 'No checkboxes found in scope' };
        }

        const unnamedCheckboxes = checkboxes
            .map((checkbox, index) => (!checkbox.name ? describeCheckbox(checkbox, index) : null))
            .filter(Boolean);
        if (unnamedCheckboxes.length === 0) {
            return { pass: true, message: 'All checkboxes have accessible names' };
        }

        return { pass: false, message: `Missing accessible names for ${summarizeList(unnamedCheckboxes)}` };
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

    await assert("Each checkbox is keyboard reachable", async () => {
        const results = await utils.testFormControls.testEachInputFocusable(page, discovery);
        return { status: results.status(), message: results.getMessage() };
    });

    await assert("Space toggles checkbox state", async () => {
        await utils.reload();
        let currentDiscovery = await utils.testFormControls.discoverCheckboxes(page);

        if (currentDiscovery.inputs.length === 0) {
            return { pass: false, message: 'No checkboxes found in scope' };
        }

        const nonInteractiveCheckboxes = currentDiscovery.inputs
            .map((checkbox, index) => ((!checkbox.visible || checkbox.disabled) ? describeCheckbox(checkbox, index) : null))
            .filter(Boolean);

        let applicableCheckboxes = 0;
        let passingCheckboxes = 0;
        const failedCheckboxes = [];

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
            } else {
                failedCheckboxes.push(describeCheckbox(checkbox, checkboxIndex));
            }
        }

        if (applicableCheckboxes === 0) {
            const suffix = nonInteractiveCheckboxes.length > 0
                ? `: ${summarizeList(nonInteractiveCheckboxes)}`
                : '';
            return { pass: false, message: `No interactive checkboxes were available for Space-key testing${suffix}` };
        }

        if (passingCheckboxes === applicableCheckboxes) {
            return { pass: true, message: 'Space toggles each checkbox state' };
        }

        return { pass: false, message: `Space did not toggle ${summarizeList(failedCheckboxes)}` };
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

        const mismatchDetails = invalidCheckboxes.map((checkbox, index) => {
            const details = (checkbox.nativeAriaStateMismatchDetails || []).join(', ');
            return `${describeCheckbox(checkbox, index)} (${details || 'state mismatch'})`;
        });
        return {
            pass: false,
            message: `Conflicting native and ARIA state on ${summarizeList(mismatchDetails)}`,
        };
    });

    await assert("Checked state is programmatically exposed", async () => {
        const checkboxes = discovery.inputs;

        if (checkboxes.length === 0) {
            return { pass: false, message: 'No checkboxes found in scope' };
        }

        const invalidCheckboxes = checkboxes
            .map((checkbox, index) => ((!checkbox.checkedStateDefined || checkbox.checkedStateMismatch) ? describeCheckbox(checkbox, index) : null))
            .filter(Boolean);
        if (invalidCheckboxes.length === 0) {
            return { pass: true, message: 'All checkboxes expose checked state programmatically' };
        }

        return { pass: false, message: `Checked state is not exposed consistently for ${summarizeList(invalidCheckboxes)}` };
    });

    return {};
};