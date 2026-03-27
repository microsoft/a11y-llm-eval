/**
 * Radio button group accessibility test assertions.
 * Supports native radios and custom ARIA radiogroups.
 */

module.exports.run = async ({ page, assert, utils }) => {
    const discovery = await utils.testFormControls.discoverRadios(page);

    await assert("Each radio has an accessible name", async () => {
        const groups = await utils.testFormControls.discoverRadioGroups(page, discovery);
        const radios = groups.flatMap((group) => group.radios);

        if (radios.length === 0) {
            return { pass: false, message: 'No radios found in scope' };
        }

        const unnamedCount = radios.filter((radio) => !radio.name).length;
        if (unnamedCount === 0) {
            return { pass: true, message: 'All radios have accessible names' };
        }

        return { pass: false, message: `${unnamedCount} radio option(s) are missing accessible names` };
    });

    await assert("Visible label is included in accessible name", async () => {
        const results = await utils.testFormControls.testLabelInName(page, discovery);
        return { pass: results.passed(), message: results.getMessage() };
    });

    await assert("Helper text is programmatically associated", async () => {
        const results = await utils.testFormControls.testHelperTextAssociated(page, discovery);
        return { pass: results.passed(), message: results.getMessage() };
    });

    await assert("Required fields are indicated (visually and programmatically)", async () => {
        const results = await utils.testFormControls.testRequiredFieldsIndicated(page, discovery);
        return { pass: results.passed(), message: results.getMessage() };
    });

    await assert("Each radio group has an accessible label", async () => {
        const groups = await utils.testFormControls.discoverRadioGroups(page, discovery);

        if (groups.length === 0) {
            return { pass: false, message: 'No radio groups found in scope' };
        }

        const unlabeledGroups = groups.filter((group) => !group.groupLabel);
        if (unlabeledGroups.length === 0) {
            return { pass: true, message: 'All radio groups have accessible labels' };
        }

        return { pass: false, message: `${unlabeledGroups.length} radio group(s) are missing accessible labels` };
    });

    await assert("Each radio group is keyboard reachable", async () => {
        const groups = await utils.testFormControls.discoverRadioGroups(page, discovery);

        if (groups.length === 0) {
            return { pass: false, message: 'No radio groups found in scope' };
        }

        const unreachableGroups = groups.filter((group) => {
            return !group.radios.some((radio) => radio.visible && !radio.disabled && radio.tabIndex >= 0);
        });

        if (unreachableGroups.length === 0) {
            return { pass: true, message: 'Each radio group has a keyboard-reachable option' };
        }

        return { pass: false, message: `${unreachableGroups.length} radio group(s) are not keyboard reachable` };
    });

    await assert("Arrow keys change the selected radio within each group", async () => {
        await utils.reload();
        let groups = await utils.testFormControls.discoverRadioGroups(page);

        if (groups.length === 0) {
            return { pass: false, message: 'No radio groups found in scope' };
        }

        let applicableGroups = 0;
        let passingGroups = 0;

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
            }
        }

        if (applicableGroups === 0) {
            return { pass: false, message: 'No multi-option radio groups were available for arrow-key testing' };
        }

        if (passingGroups === applicableGroups) {
            return { pass: true, message: 'Arrow keys update selection in each radio group' };
        }

        return { pass: false, message: `${applicableGroups - passingGroups} radio group(s) did not update selection on arrow keys` };
    });

    await assert("Checked state is programmatically exposed", async () => {
        const groups = await utils.testFormControls.discoverRadioGroups(page, discovery);
        const radios = groups.flatMap((group) => group.radios);

        if (radios.length === 0) {
            return { pass: false, message: 'No radios found in scope' };
        }

        const invalidCount = radios.filter((radio) => !radio.checkedStateDefined).length;
        if (invalidCount === 0) {
            return { pass: true, message: 'All radios expose checked state programmatically' };
        }

        return { pass: false, message: `${invalidCount} radio option(s) do not expose checked state programmatically` };
    });

    return {};
};