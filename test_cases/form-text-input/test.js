/**
 * Form Text Input accessibility test assertions
 * Tests WCAG 4.1.2, 2.1.1, 2.4.7, 1.3.1, 3.3.2
 */

module.exports.run = async ({ page, assert, utils }) => {

    // Assertion 1: Each text input has an accessible name (R - WCAG 4.1.2, 1.3.1, 3.3.2)
    await assert("Each text input has an accessible name", async () => {
        const results = await utils.testTextInputs.testEachInputHasName(page);
        return { pass: results.passed(), message: results.getMessage() };
    });

    // Assertion 2: Each text input has textbox role (R - WCAG 4.1.2)
    // Check that form fields intended for text input contain proper textbox elements
    await assert("Each text input has textbox role", async () => {
        const results = await utils.testTextInputs.testEachInputHasRole(page);
        return { pass: results.passed(), message: results.getMessage() };
    });

    // Assertion 3: Helper text is programmatically associated (R - WCAG 1.3.1)
    await assert("Helper text is programmatically associated", async () => {
        const results = await utils.testTextInputs.testHelperTextAssociated(page);
        return { pass: results.passed(), message: results.getMessage() };
    });

    // Assertion 4: Text inputs are keyboard focusable (R - WCAG 2.1.1)
    await assert("Text inputs are keyboard focusable", async () => {
        const results = await utils.testTextInputs.testEachInputFocusable(page);
        return { pass: results.passed(), message: results.getMessage() };
    });

    // Assertion 5: tests that Visual labels are defined and persistant (R - WCAG 2.4.6)
    await assert("Visual labels are defined and persistant", async () => {
        const results = await utils.testTextInputs.testEachInputHasLabel(page);
        return { pass: results.passed(), message: results.getMessage() };
    });

    // Assertion 6: Required fields are programmatically indicated (BP - WCAG 3.3.2)
    await assert("Required fields are programmatically indicated", async () => {
        const results = await utils.testTextInputs.testRequiredFieldsIndicated(page);
        return { pass: results.passed(), message: results.getMessage() };
    }, { type: 'BP' });

    return {}; // assertions collected via injected assert
};
