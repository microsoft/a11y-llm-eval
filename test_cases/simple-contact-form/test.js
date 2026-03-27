/**
 * Form Text Input accessibility test assertions
 * Tests WCAG 4.1.2, 2.1.1, 2.4.7, 1.3.1, 3.3.2
 */

// Using shared discovery cache from utils.testFormControls to avoid repeated scans

module.exports.run = async ({ page, assert, utils }) => {

    // Prime a single-pass discovery to share across checks
    const discovery = await utils.testFormControls.discoverTextInputs(page);

    // Assertion 1: Each text input has an accessible name (R - WCAG 4.1.2, 1.3.1, 3.3.2)
    await assert("Each text input has an accessible name", async () => {
        const results = await utils.testFormControls.testEachInputHasName(page, discovery);
        return { pass: results.passed(), message: results.getMessage() };
    });

    // Assertion 2: Visible label text is included in accessible name (R - WCAG 2.5.3)
    await assert("Visible label is included in accessible name", async () => {
        const results = await utils.testFormControls.testLabelInName(page, discovery);
        return { status: results.status(), message: results.getMessage() };
    });

    // Assertion 3: Each text input has textbox role (R - WCAG 4.1.2)
    // Check that form fields intended for text input contain proper textbox elements
    await assert("Each text input has textbox role", async () => {
        const formFields = discovery.wrappers;

        // Compute required counts with no element-handle loops.
        const withTextbox = formFields.filter({ has: page.getByRole('textbox') });

        // Prefer hasNot for Playwright >= 1.37; fallback to CSS :has if needed.
        const buttonOnly = formFields
            .filter({ has: page.getByRole('button') })
            .filter({ hasNot: page.getByRole('textbox') });

        const [fieldCount, textInputFields, totalButtonOnly] = await Promise.all([
            formFields.count(),
            withTextbox.count(),
            buttonOnly.count(),
        ]);

        if (fieldCount === 0) {
            return { pass: false, message: "No form fields found in scope" };
        }
        if (textInputFields === 0) {
            return { pass: false, message: "No text input fields found in scope" };
        }
        if (textInputFields === fieldCount - totalButtonOnly) {
            return { pass: true, message: "Text input fields with textbox role found" };
        }
        return { pass: false, message: "Some text input fields do not have textbox role" };
    });

    // Assertion 4: Helper text is programmatically associated (R - WCAG 1.3.1)
    await assert("Helper text is programmatically associated", async () => {
        const results = await utils.testFormControls.testHelperTextAssociated(page, discovery);
        return { status: results.status(), message: results.getMessage() };
    });

    // Assertion 5: Text inputs are keyboard focusable (R - WCAG 2.1.1)
    await assert("Text inputs are keyboard focusable", async () => {
        const results = await utils.testFormControls.testEachInputFocusable(page, discovery);
        return { pass: results.passed(), message: results.getMessage() };
    });

    // Assertion 6: tests that Visual labels are defined and persistent (R - WCAG 3.3.2)
    await assert("Visual labels are defined and persistent", async () => {
        const results = await utils.testFormControls.testEachInputHasPersistentVisualLabel(page, discovery);
        return { pass: results.passed(), message: results.getMessage() };
    });

    // Assertion 7: Required fields are indicated (visually and programmatically) (R - WCAG 3.3.2, 4.1.2)
    await assert("Required fields are indicated (visually and programmatically)", async () => {
        const results = await utils.testFormControls.testRequiredFieldsIndicated(page, discovery);
        return { status: results.status(), message: results.getMessage() };
    });

    // Assertion 8: Inputs use appropriate autocomplete for purpose (R - WCAG 1.3.5)
    await assert("Inputs use appropriate autocomplete for purpose", async () => {
        const results = await utils.testFormControls.testIdentifyInputPurposeAutocomplete(page, discovery);
        return { status: results.status(), message: results.getMessage() };
    });

    // Assertion 9: Placeholder text is programmatically defined as a property (R - WCAG 4.1.2)
    await assert("Placeholder text is programmatically defined as a property", async () => {
        const results = await utils.testFormControls.testPlaceholderTextDefined(page, discovery);
        return { status: results.status(), message: results.getMessage() };
    });

    return {}; // assertions collected via injected assert
};
