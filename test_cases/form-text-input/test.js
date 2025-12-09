/**
 * Form Text Input accessibility test assertions
 * Tests WCAG 4.1.2, 2.1.1, 2.4.7, 1.3.1, 3.3.2
 */

/**
 * Get all text inputs including native inputs, textareas, and custom implementations
 */
const getTextInputs = async (page) => {
    // Native text-like inputs
    const nativeInputs = 'input[type="text"], input[type="email"], input[type="tel"], input:not([type])';

    // Textarea (may be used for any text field)
    const textareas = 'textarea';

    // Custom implementations - contenteditable or role="textbox"
    // Scoped to .form-field to avoid matching unrelated editable regions
    const customInputs = '.form-field [contenteditable="true"], .form-field [contenteditable="plaintext-only"], .form-field [role="textbox"]';

    return await page.locator(`${nativeInputs}, ${textareas}, ${customInputs}`).filter({ visible: true });
};

/**
 * Get all form field wrappers
 */
const getFormFields = async (page) => {
    return await page.locator('.form-field');
};

module.exports.run = async ({ page, assert, utils }) => {

    // Assertion 1: Each text input has an accessible name (R - WCAG 4.1.2, 1.3.1)
    await assert("Each text input has an accessible name", async () => {
        const inputs = await getTextInputs(page);
        const count = await inputs.count();

        if (count === 0) {
            return { pass: false, message: "No text inputs found on the page" };
        }

        let passCount = 0;
        for (let i = 0; i < count; i++) {
            const input = inputs.nth(i);

            const hasAccessibleName = await input.evaluate((el) => {
                // Method 1: Check the labels property (works for <label for="id"> and wrapped labels)
                if (el.labels && el.labels.length > 0) {
                    return el.labels[0].textContent.trim().length > 0;
                }

                // Method 2: Check aria-label
                if (el.getAttribute('aria-label') && el.getAttribute('aria-label').trim().length > 0) {
                    return true;
                }

                // Method 3: Check aria-labelledby
                const labelledbyId = el.getAttribute('aria-labelledby');
                if (labelledbyId) {
                    const ids = labelledbyId.split(' ');
                    for (const id of ids) {
                        const labelElement = document.getElementById(id);
                        if (labelElement && labelElement.textContent.trim().length > 0) {
                            return true;
                        }
                    }
                }

                // Method 4: Check title attribute as fallback (not recommended but valid)
                if (el.getAttribute('title') && el.getAttribute('title').trim().length > 0) {
                    return true;
                }

                return false;
            });

            if (hasAccessibleName) {
                passCount++;
            }
        }

        return passCount === count;
    });

    // Assertion 2: Each text input has textbox role (R - WCAG 4.1.2)
    await assert("Each text input has textbox role", async () => {
        const inputs = await getTextInputs(page);
        const count = await inputs.count();

        if (count === 0) {
            return { pass: false, message: "No text inputs found on the page" };
        }

        let validRoleCount = 0;

        for (let i = 0; i < count; i++) {
            const input = inputs.nth(i);

            const hasTextboxRole = await input.evaluate((el) => {
                // Native inputs and textareas implicitly have textbox role
                const tagName = el.tagName.toLowerCase();
                if (tagName === 'input' || tagName === 'textarea') {
                    return true;
                }

                // Custom elements need explicit role="textbox"
                const role = el.getAttribute('role');
                return role === 'textbox';
            });

            if (hasTextboxRole) {
                validRoleCount++;
            }
        }

        return validRoleCount === count;
    });

    // Assertion 3: Helper text is programmatically associated (R - WCAG 1.3.1)
    await assert("Helper text is programmatically associated", async () => {
        const formFields = await getFormFields(page);
        const fieldCount = await formFields.count();

        if (fieldCount === 0) {
            return { pass: false, message: "No form fields found" };
        }

        let fieldsWithHelperText = 0;
        let fieldsWithAssociatedHelper = 0;

        for (let i = 0; i < fieldCount; i++) {
            const field = formFields.nth(i);

            const helperInfo = await field.evaluate((el) => {
                const input = el.querySelector('input');
                const label = el.querySelector('label');

                if (!input) return { hasHelper: false, isAssociated: false };

                // Find potential helper text elements
                const helperSelectors = [
                    '[class*="helper"]',
                    '[class*="hint"]',
                    '[class*="description"]',
                    '[class*="help"]',
                    'small',
                    '.form-text',
                    'p:not(:empty)'
                ];

                let helperElement = null;
                for (const selector of helperSelectors) {
                    const el2 = el.querySelector(selector);
                    if (el2 && el2 !== label && !el2.contains(input)) {
                        helperElement = el2;
                        break;
                    }
                }

                // Also check for text content outside label/input
                if (!helperElement) {
                    const allText = el.textContent || '';
                    const labelText = label ? label.textContent : '';
                    const inputValue = input.value || '';
                    const remainingText = allText.replace(labelText, '').replace(inputValue, '').trim();

                    if (remainingText.length > 10) {
                        // There's significant text that might be helper text
                        // Check if any element contains it
                        const children = el.querySelectorAll('*');
                        for (const child of children) {
                            if (child !== label && child !== input && !label?.contains(child) &&
                                child.textContent.trim().length > 10 &&
                                child.children.length === 0) {
                                helperElement = child;
                                break;
                            }
                        }
                    }
                }

                if (!helperElement) {
                    return { hasHelper: false, isAssociated: true };
                }

                // Check if helper text is associated via aria-describedby
                const describedbyId = input.getAttribute('aria-describedby');
                if (!describedbyId) {
                    return { hasHelper: true, isAssociated: false };
                }

                // Verify the referenced element exists
                const ids = describedbyId.split(' ');
                for (const id of ids) {
                    const describingEl = document.getElementById(id);
                    if (describingEl && describingEl.textContent.trim().length > 0) {
                        return { hasHelper: true, isAssociated: true };
                    }
                }

                return { hasHelper: true, isAssociated: false };
            });

            if (helperInfo.hasHelper) {
                fieldsWithHelperText++;
                if (helperInfo.isAssociated) {
                    fieldsWithAssociatedHelper++;
                }
            }
        }

        // If there's helper text, it must be associated
        // If no helper text found, pass (nothing to associate)
        if (fieldsWithHelperText === 0) {
            return { pass: true, message: "No helper text found to associate" };
        }

        return fieldsWithAssociatedHelper === fieldsWithHelperText;
    });

    // Assertion 4: Text inputs are keyboard focusable (R - WCAG 2.1.1)
    await assert("Text inputs are keyboard focusable", async () => {
        const inputs = await getTextInputs(page);
        const count = await inputs.count();

        if (count === 0) {
            return { pass: false, message: "No text inputs found on the page" };
        }

        let focusableCount = 0;

        for (let i = 0; i < count; i++) {
            const input = inputs.nth(i);

            const isFocusable = await input.evaluate((el) => {
                const tabindex = el.getAttribute('tabindex');
                const isDisabled = el.disabled;
                const isHidden = el.type === 'hidden';

                // tabindex >= 0 or no tabindex (defaults to focusable for inputs)
                const hasFocusableTabindex = tabindex === null || parseInt(tabindex, 10) >= 0;

                return hasFocusableTabindex && !isDisabled && !isHidden;
            });

            if (isFocusable) {
                focusableCount++;
            }
        }

        return focusableCount === count;
    });

    // Assertion 5: Input labels are visible (BP - WCAG 2.4.6)
    await assert("Input labels are visible", async () => {
        const inputs = await getTextInputs(page);
        const count = await inputs.count();

        if (count === 0) {
            return { pass: false, message: "No text inputs found on the page" };
        }

        let visibleLabelCount = 0;

        for (let i = 0; i < count; i++) {
            const input = inputs.nth(i);

            const hasVisibleLabel = await input.evaluate((el) => {
                // Check for visible <label> element
                if (el.labels && el.labels.length > 0) {
                    const label = el.labels[0];
                    const style = window.getComputedStyle(label);
                    const isVisible = style.display !== 'none' &&
                        style.visibility !== 'hidden' &&
                        style.opacity !== '0' &&
                        label.offsetWidth > 0 &&
                        label.offsetHeight > 0;
                    return isVisible;
                }

                // Check for aria-labelledby referencing a visible element
                const labelledbyId = el.getAttribute('aria-labelledby');
                if (labelledbyId) {
                    const ids = labelledbyId.split(' ');
                    for (const id of ids) {
                        const labelElement = document.getElementById(id);
                        if (labelElement) {
                            const style = window.getComputedStyle(labelElement);
                            if (style.display !== 'none' &&
                                style.visibility !== 'hidden' &&
                                style.opacity !== '0' &&
                                labelElement.offsetWidth > 0 &&
                                labelElement.offsetHeight > 0) {
                                return true;
                            }
                        }
                    }
                }

                return false;
            });

            if (hasVisibleLabel) {
                visibleLabelCount++;
            }
        }

        return visibleLabelCount === count;
    }, { type: 'BP' });

    // Assertion 6: Required fields are programmatically indicated (BP - WCAG 3.3.2)
    await assert("Required fields are programmatically indicated", async () => {
        const inputs = await getTextInputs(page);
        const count = await inputs.count();

        if (count === 0) {
            return { pass: false, message: "No text inputs found on the page" };
        }

        // Check if any inputs appear to be required (by visual indicators or context)
        // and verify they have proper programmatic indication
        let visuallyRequiredCount = 0;
        let programmaticallyIndicatedCount = 0;

        for (let i = 0; i < count; i++) {
            const input = inputs.nth(i);

            const requiredInfo = await input.evaluate((el) => {
                const hasRequiredAttr = el.hasAttribute('required');
                const hasAriaRequired = el.getAttribute('aria-required') === 'true';
                const isProgrammaticallyRequired = hasRequiredAttr || hasAriaRequired;

                // Check for visual required indicators
                // Look for asterisk (*) near the input or in its label
                let hasVisualIndicator = false;

                if (el.labels && el.labels.length > 0) {
                    const labelText = el.labels[0].textContent || '';
                    hasVisualIndicator = labelText.includes('*') ||
                                        labelText.toLowerCase().includes('required');
                }

                // Also check parent form-field wrapper
                const formField = el.closest('.form-field');
                if (formField) {
                    const fieldText = formField.textContent || '';
                    hasVisualIndicator = hasVisualIndicator ||
                                        fieldText.includes('*') ||
                                        fieldText.toLowerCase().includes('required');
                }

                return {
                    visuallyRequired: hasVisualIndicator,
                    programmaticallyRequired: isProgrammaticallyRequired
                };
            });

            if (requiredInfo.visuallyRequired) {
                visuallyRequiredCount++;
                if (requiredInfo.programmaticallyRequired) {
                    programmaticallyIndicatedCount++;
                }
            }
        }

        // If fields appear required visually, they should be programmatically indicated
        // If no visually required fields, we pass (nothing to check)
        if (visuallyRequiredCount === 0) {
            return { pass: true, message: "No visually required fields found" };
        }

        return programmaticallyIndicatedCount === visuallyRequiredCount;
    }, { type: 'BP' });

    return {}; // assertions collected via injected assert
};
