/**
 * Radio button group accessibility test assertions.
 * Supports native radios and custom ARIA radiogroups.
 */

const normalizeText = (value) => (value || '').toString().replace(/[\s\u00A0]+/g, ' ').trim();
const summarizeList = (items, maxItems = 4) => {
    const filtered = items.filter(Boolean);
    if (filtered.length <= maxItems) {
        return filtered.join(', ');
    }
    return `${filtered.slice(0, maxItems).join(', ')}, and ${filtered.length - maxItems} more`;
};
const describeRadio = (radio, index) => {
    const label = normalizeText((radio.visualLabel && radio.visualLabel.text) || radio.name);
    const groupLabel = normalizeText(radio.groupLabel);
    if (label && groupLabel) {
        return `radio "${label}" in group "${groupLabel}"`;
    }
    if (label) {
        return `radio "${label}"`;
    }
    return `radio ${index + 1}`;
};
const describeGroup = (group, index) => {
    const label = normalizeText(group.groupLabel);
    return label ? `radio group "${label}"` : `radio group ${index + 1}`;
};

module.exports.run = async ({ page, assert, utils }) => {
    const discovery = await utils.testFormControls.discoverRadios(page);

    await assert("Each radio has an accessible name", async () => {
        const groups = await utils.testFormControls.discoverRadioGroups(page, discovery);
        const radios = groups.flatMap((group) => group.radios);

        if (radios.length === 0) {
            return { pass: false, message: 'No radios found in scope' };
        }

        const unnamedRadios = radios
            .map((radio, index) => (!radio.name ? describeRadio(radio, index) : null))
            .filter(Boolean);
        if (unnamedRadios.length === 0) {
            return { pass: true, message: 'All radios have accessible names' };
        }

        return { pass: false, message: `Missing accessible names for ${summarizeList(unnamedRadios)}` };
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

    await assert("Each radio group has an accessible label", async () => {
        const groups = await utils.testFormControls.discoverRadioGroups(page, discovery);

        if (groups.length === 0) {
            return { pass: false, message: 'No radio groups found in scope' };
        }

        const unlabeledGroups = groups
            .map((group, index) => (!group.groupLabel ? describeGroup(group, index) : null))
            .filter(Boolean);
        if (unlabeledGroups.length === 0) {
            return { pass: true, message: 'All radio groups have accessible labels' };
        }

        return { pass: false, message: `Missing accessible labels for ${summarizeList(unlabeledGroups)}` };
    });

    await assert("Each radio group is keyboard reachable", async () => {
        const groups = await utils.testFormControls.discoverRadioGroups(page, discovery);

        if (groups.length === 0) {
            return { pass: false, message: 'No radio groups found in scope' };
        }

        const unreachableGroups = groups
            .map((group, index) => {
                const reachable = group.radios.some((radio) => radio.visible && !radio.disabled && radio.tabIndex >= 0);
                return reachable ? null : describeGroup(group, index);
            })
            .filter(Boolean);

        if (unreachableGroups.length === 0) {
            return { pass: true, message: 'Each radio group has a keyboard-reachable option' };
        }

        return { pass: false, message: `Not keyboard reachable: ${summarizeList(unreachableGroups)}` };
    });

    await assert("Arrow keys change the selected radio within each group", async () => {
        await utils.reload();
        let groups = await utils.testFormControls.discoverRadioGroups(page);

        if (groups.length === 0) {
            return { pass: false, message: 'No radio groups found in scope' };
        }

        const nonInteractiveGroups = groups
            .map((group, index) => {
                const interactiveRadios = group.radios.filter((radio) => radio.visible && !radio.disabled);
                return interactiveRadios.length < 2 ? describeGroup(group, index) : null;
            })
            .filter(Boolean);

        let applicableGroups = 0;
        let passingGroups = 0;
        const failedGroups = [];

        for (let groupIndex = 0; groupIndex < groups.length; groupIndex += 1) {
            await utils.reload();
            groups = await utils.testFormControls.discoverRadioGroups(page);
            const group = groups[groupIndex];
            if (!group) {
                continue;
            }

            const interactiveRadios = group.radios.filter((radio) => radio.visible && !radio.disabled);
            if (interactiveRadios.length < 2) {
                continue;
            }

            applicableGroups += 1;

            const target = interactiveRadios.find((radio) => radio.checked) || interactiveRadios[0];
            const locator = page.locator('input[type="radio"], [role="radio"]').nth(target.domIndex);
            await locator.focus();

            const before = utils.testFormControls.getCheckedRadioIndexes(group).join(',');

            await locator.press('ArrowRight');
            await page.waitForTimeout(30);

            let updatedGroups = await utils.testFormControls.discoverRadioGroups(page);
            let after = updatedGroups[groupIndex] ? utils.testFormControls.getCheckedRadioIndexes(updatedGroups[groupIndex]).join(',') : before;

            if (after === before) {
                await locator.press('ArrowDown');
                await page.waitForTimeout(30);
                updatedGroups = await utils.testFormControls.discoverRadioGroups(page);
                after = updatedGroups[groupIndex] ? utils.testFormControls.getCheckedRadioIndexes(updatedGroups[groupIndex]).join(',') : before;
            }

            if (after && after !== before) {
                passingGroups += 1;
            } else {
                failedGroups.push(describeGroup(group, groupIndex));
            }
        }

        if (applicableGroups === 0) {
            const suffix = nonInteractiveGroups.length > 0
                ? `: ${summarizeList(nonInteractiveGroups)}`
                : '';
            return { pass: false, message: `No multi-option radio groups were available for arrow-key testing${suffix}` };
        }

        if (passingGroups === applicableGroups) {
            return { pass: true, message: 'Arrow keys update selection in each radio group' };
        }

        return { pass: false, message: `Arrow keys did not update selection for ${summarizeList(failedGroups)}` };
    });

    await assert("ARIA attributes match native radio attributes if used", async () => {
        const groups = await utils.testFormControls.discoverRadioGroups(page, discovery);
        const radios = groups.flatMap((group) => group.radios);

        if (radios.length === 0) {
            return { pass: false, message: 'No radios found in scope' };
        }

        const invalidRadios = radios.filter((radio) => radio.hasNativeAriaStateMismatch);
        if (invalidRadios.length === 0) {
            return { pass: true, message: 'ARIA state is consistent with native radio state' };
        }

        const mismatchDetails = invalidRadios.map((radio, index) => {
            const details = (radio.nativeAriaStateMismatchDetails || []).join(', ');
            return `${describeRadio(radio, index)} (${details || 'state mismatch'})`;
        });
        return {
            pass: false,
            message: `Conflicting native and ARIA state on ${summarizeList(mismatchDetails)}`,
        };
    });

    await assert("Checked state is programmatically exposed", async () => {
        const groups = await utils.testFormControls.discoverRadioGroups(page, discovery);
        const radios = groups.flatMap((group) => group.radios);

        if (radios.length === 0) {
            return { pass: false, message: 'No radios found in scope' };
        }

        const invalidRadios = radios
            .map((radio, index) => ((!radio.checkedStateDefined || radio.checkedStateMismatch) ? describeRadio(radio, index) : null))
            .filter(Boolean);
        if (invalidRadios.length === 0) {
            return { pass: true, message: 'All radios expose checked state programmatically' };
        }

        return { pass: false, message: `Checked state is not exposed consistently for ${summarizeList(invalidRadios)}` };
    });

    return {};
};