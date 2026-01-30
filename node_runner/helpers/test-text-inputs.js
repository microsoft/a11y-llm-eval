
const detailedResults = require('./detailed-results');
const { getVisualLabel, SOURCE_PLACEHOLDER } = require('./get-visual-label');
const { getAllFormFieldWrappers } = require('./get-form-field-wrapper');
const { combineHelperTexts, getHelperText, SOURCE_ARIA_DESCRIBEDBY, SOURCE_TITLE, SOURCE_CSS_PLACEHOLDER } = require('./get-helper-text');
const { discover } = require('./discovery');

let testFn = {};

// Get all text inputs
const getTextInputs = async (scope) => {
    return scope.getByRole('textbox');
};

// Get all form field wrappers
const getFormFields = async (scope) => {
    return await getAllFormFieldWrappers(scope);
};

// Check that each text input has an accessible name (R - WCAG 4.1.2)
testFn.testEachInputHasName = async (scope, discoveryCache) => {
    let results = new detailedResults();
    const d = discoveryCache || await discover(scope);
    const count = d.inputs.length;

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    for (const item of d.inputs) {
        const name = item.name;
        if (name && name.trim().length > 0) {
            results.addPass(item.locator);
        } else {
            results.addFail(item.locator);
        }
    }

    return results;
}

// Check that helper text is programmatically associated (R - WCAG 1.3.1)
testFn.testHelperTextAssociated = async (scope, discoveryCache) => {
    let results = new detailedResults();
    const d = discoveryCache || await discover(scope);
    const count = d.inputs.length;

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    const isTrivialHelperText = (txt) => {
        if (!txt) return true;
        const t = txt.trim();
        if (!t) return true;
        if (t.length === 1) return true; // treat single-character hints (e.g., '*') as trivial
        return false;
    };

    for (const item of d.inputs) {
        const helpers = Array.isArray(item.helperText)
            ? item.helperText
            : (item.helperText ? [item.helperText] : []);

        const meaningfulHelpers = helpers.filter(h => !isTrivialHelperText(h && h.text));

        if (meaningfulHelpers.length === 0) {
            continue; // no meaningful helper text to check
        }

        const hasProgrammaticAssociation = meaningfulHelpers.some(h =>
            h && (h.source === SOURCE_ARIA_DESCRIBEDBY || h.source === SOURCE_TITLE)
        );

        if (hasProgrammaticAssociation) {
            results.addPass(item.locator);
        } else {
            results.addFail(item.locator);
            results.addMessage("Found `" + combineHelperTexts(meaningfulHelpers) + "`");
        }
    }

    return results;
}

// Check that text inputs are keyboard focusable (R - WCAG 2.1.1)
testFn.testEachInputFocusable = async (scope, discoveryCache) => {
    let results = new detailedResults();
    const d = discoveryCache || await discover(scope);
    const count = d.inputs.length;

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    for (const item of d.inputs) {
        if (!item.visible) {
            continue; // skip hidden inputs
        }
        const tabindex = item.tabIndex;
        const isKeyboardNavigable = tabindex === null || parseInt(tabindex, 10) >= 0;
        if (isKeyboardNavigable) {
            results.addPass(item.locator);
        } else {
            results.addFail(item.locator);
        }
    }

    return results;
}

// Check that placeholder text is programmatically defined as a property (R - WCAG 4.1.2)
// Accepts native `placeholder` and ARIA `aria-placeholder` attributes as valid.
// Flags cases where a control appears to use a non-standard placeholder attribute
// (e.g., `data-placeholder`) without also providing a standard programmatic property.
testFn.testPlaceholderTextDefined = async (scope, discoveryCache) => {
    let results = new detailedResults();
    const d = discoveryCache || await discover(scope);
    const count = d.inputs.length;

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    let applicable = 0;

    for (const item of d.inputs) {
        const placeholder = item.placeholder;
        const ariaPlaceholder = item.ariaPlaceholder;

        const hasStandardPlaceholder = (
            (placeholder !== null && placeholder !== undefined) ||
            (ariaPlaceholder !== null && ariaPlaceholder !== undefined)
        );

        const helpers = Array.isArray(item.helperText)
            ? item.helperText
            : (item.helperText ? [item.helperText] : []);

        const hasCssPlaceholder = helpers.some(h => h && h.source === SOURCE_CSS_PLACEHOLDER && h.text);

        if (!hasStandardPlaceholder && !hasCssPlaceholder) {
            // No placeholder-related behavior; nothing to check for this field.
            continue;
        }

        applicable++;

        if (hasCssPlaceholder && !hasStandardPlaceholder) {
            // Placeholder-like text rendered only via CSS pseudo-elements,
            // with no programmatic placeholder or aria-placeholder property.
            results.addFail(item.locator);
            results.addMessage("Found CSS placeholder text without programmatic placeholder property");
        } else if (hasStandardPlaceholder) {
            // Placeholder text is exposed via a proper property.
            results.addPass(item.locator);
        }
    }

    if (applicable === 0) {
        results.addMessage("No placeholder text present on text inputs");
        results.forcePass();
    }

    return results;
}

// Check that persistent visible labels are defined (R - WCAG 3.3.2)
// This does not consider placeholder-only labels as persistent visible labels, and does not check for programmatic association
testFn.testEachInputHasPersistentVisualLabel = async (scope, discoveryCache) => {
    let results = new detailedResults();
    const d = discoveryCache || await discover(scope);
    const count = d.inputs.length;

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    for (const item of d.inputs) {
        const visualLabel = item.visualLabel;
        if (visualLabel && visualLabel.text.trim().length > 0 && visualLabel.source !== SOURCE_PLACEHOLDER) {
            results.addPass(item.locator);
        } else {
            results.addFail(item.locator);
        }
    }

    return results;
}


// Check if any inputs appear to be required (by visual indicators in label/help)
// and verify they have proper programmatic indication
testFn.testRequiredFieldsIndicated = async (scope, discoveryCache) => {
    let results = new detailedResults();
    const d = discoveryCache || await discover(scope);
    const count = d.inputs.length;

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    // Helper to detect an asterisk at start or end of a label
    const hasAsteriskRequiredIndicator = (labelObj) => {
        if (!labelObj || !labelObj.text) return false;
        const text = labelObj.text.trim();
        // Allow optional punctuation/colon around the asterisk
        return text.startsWith('*') || text.endsWith('*');
    };

    // Helper to detect textual indicators for required while avoiding content descriptions
    const hasTextualRequiredIndicator = (rawText) => {
        if (!rawText) return false;
        const t = String(rawText).toLowerCase().trim();

        // Strong signals first
        if (/\(\s*required\s*\)/.test(t)) return true; // '(required)'
        if (/\bmandatory\b/.test(t)) return true;        // 'mandatory'

        // Phrases that indicate the field itself is required
        if (/\bis required\b/.test(t)) return true;      // 'is required'
        if (/\brequired field\b/.test(t)) return true;   // 'required field'

        // Trailing 'required' at the end of the string (optionally with punctuation)
        if (/(^|\s)required[\s\.!?)]*$/.test(t)) return true;

        // Avoid cases like 'required length', 'required format', etc., where 'required'
        // describes the content rather than the field requirement.
        if (/\brequired\s+(length|format|characters?|fields?|value|values|minimum|password|pattern|items?)\b/.test(t)) {
            return false;
        }

        return false;
    };

    let visuallyRequiredCount = 0;
    let programmaticallyRequiredCount = 0;

    for (const item of d.inputs) {
        const isProgrammaticallyRequired = item.programmaticallyRequired;
        const label = item.visualLabel;
        const helpers = Array.isArray(item.helperText)
            ? item.helperText
            : (item.helperText ? [item.helperText] : []);

        // Determine if this field looks required based on the label/help text
        const labelIndicatesRequired = hasAsteriskRequiredIndicator(label) || hasTextualRequiredIndicator(label?.text);

        let helpTextIndicatesRequired = false;
        for (const h of helpers) {
            if (!h) continue;
            if (hasAsteriskRequiredIndicator(h) || hasTextualRequiredIndicator(h.text)) {
                helpTextIndicatesRequired = true;
                break;
            }
        }
        const hasVisualIndicator = labelIndicatesRequired || helpTextIndicatesRequired;

        if (hasVisualIndicator) {
            visuallyRequiredCount++;
            if (isProgrammaticallyRequired) {
                results.addPass(item.locator);
            } else {
                results.addFail(item.locator);
            }
        } else if (isProgrammaticallyRequired) {
            programmaticallyRequiredCount++;
            // Programmatically required but no visual indicator
            results.addFail(item.locator);
            results.addMessage("Input is programmatically required but has no visual required indicator");
        }
    }

    // If fields appear required visually, they should be programmatically indicated
    // If no visually required fields, we pass (nothing to check)
    if (visuallyRequiredCount === 0 && programmaticallyRequiredCount === 0) {
        results.addMessage("No visually required fields found");
        results.forcePass();
    }

    return results;
}

// Check that visible label text is included in the accessible name (R - WCAG 2.5.3)
testFn.testLabelInName = async (scope, discoveryCache) => {
    let results = new detailedResults();
    const d = discoveryCache || await discover(scope);
    const count = d.inputs.length;

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    // Normalize helper: collapse whitespace, lowercase
    const norm = (s) => (s || '')
        .replace(/[\s\u00A0]+/g, ' ')
        .trim()
        .toLowerCase();

    // Strip common non-essential indicators from the visible label (e.g., '*', trailing ':', '(required)')
    const stripLabelNoise = (s) => {
        if (!s) return '';
        let t = s.replace(/\(\s*required\s*\)/gi, '');
        t = t.replace(/\brequired\b/gi, '');
        t = t.replace(/^\*+|\*+$/g, '');
        t = t.replace(/[:：]\s*$/g, '');
        return t;
    };

    // Only applies when there is a visible text label (not placeholder-only)
    let applicable = 0;
    for (const item of d.inputs) {
        const vl = item.visualLabel;
        if (!vl || !vl.text || !vl.text.trim()) {
            continue; // no visible text label
        }
        applicable++;

        const labelText = stripLabelNoise(vl.text);
        const nameText = item.name || '';

        const labelNorm = norm(labelText);
        const nameNorm = norm(nameText);

        // Accessible name should contain the visible label text in the same order
        if (labelNorm && nameNorm.includes(labelNorm)) {
            results.addPass(item.locator);
        } else {
            results.addFail(item.locator);
        }
    }

    if (applicable === 0) {
        // Nothing to check; treat as pass with context message
        results.addMessage("No inputs with visible text labels applicable to 2.5.3");
        results.forcePass();
    }

    return results;
}

// Expose discovery so callers can prime and pass a cache
testFn.discover = discover;

// Check that inputs use appropriate autocomplete values for their inferred purpose (R - WCAG 1.3.5)
testFn.testIdentifyInputPurposeAutocomplete = async (scope, discoveryCache) => {
    let results = new detailedResults();
    const d = discoveryCache || await discover(scope);
    const count = d.inputs.length;

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    // Infer expected autocomplete from visible label or accessible name
    const inferExpectedAutocomplete = (nameText, labelObj) => {
        const parts = [];
        if (labelObj && labelObj.text) parts.push(labelObj.text);
        if (nameText) parts.push(nameText);
        const t = parts.join(' ').toLowerCase();

        // Word-boundary helpers to avoid substring false-positives (e.g., 'tel' vs 'tell')
        const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const hasWord = (text, word) => new RegExp(`\\b${esc(word)}\\b`, 'i').test(text);
        const hasAnyWord = (text, words) => words.some(w => hasWord(text, w));
        const hasPhrase = (text, phrase) => new RegExp(`\\b${esc(phrase)}\\b`, 'i').test(text);

        // Strong matches first
        if (hasWord(t, 'email')) return ['email'];
        if (hasAnyWord(t, ['telephone', 'phone'])) {
            // Specialized phone subfields
            if (hasWord(t, 'extension')) return ['tel-extension'];
            if (hasPhrase(t, 'country code')) return ['tel-country-code'];
            if (hasPhrase(t, 'area code')) return ['tel-area-code'];
            if (hasWord(t, 'local')) return ['tel-local'];
            if (hasWord(t, 'national')) return ['tel-national'];
            return ['tel'];
        }

        // Names
        if (hasPhrase(t, 'first name')) return ['given-name'];
        if (hasPhrase(t, 'middle name') || hasPhrase(t, 'additional name')) return ['additional-name'];
        if (hasPhrase(t, 'last name') || hasWord(t, 'surname') || hasPhrase(t, 'family name')) return ['family-name'];
        if (hasWord(t, 'username')) return ['username'];
        if (hasWord(t, 'nickname')) return ['nickname'];
        // Generic name: accept any of the name tokens
        if (hasPhrase(t, 'full name') || (hasWord(t, 'name') && !hasWord(t, 'user'))) {
            return ['name', 'given-name', 'family-name'];
        }

        // Address lines and street
        if (hasPhrase(t, 'address line 1') || hasPhrase(t, 'address 1')) return ['address-line1'];
        if (hasPhrase(t, 'address line 2') || hasPhrase(t, 'address 2')) return ['address-line2'];
        if (hasPhrase(t, 'address line 3') || hasPhrase(t, 'address 3')) return ['address-line3'];
        if (hasPhrase(t, 'street address') || (hasWord(t, 'street') && hasWord(t, 'address'))) return ['street-address'];
        if (hasWord(t, 'address') && !hasWord(t, 'email')) return ['street-address', 'address-line1'];

        // City / State / Region
        if (/(^|\b)(city|town|municipality)(\b|$)/i.test(t)) return ['address-level2'];
        if (/(^|\b)(state|province|region|county)(\b|$)/i.test(t) && !hasPhrase(t, 'united states')) return ['address-level1'];

        // Postal code synonyms
        if (/(^|\b)(postal\s*code|postcode|zip\s*code|zipcode|zip|pin\s*code|pincode)(\b|$)/i.test(t)) return ['postal-code'];

        // Country
        if (/(^|\b)(country|nation)(\b|$)/i.test(t)) return ['country', 'country-name'];

        // Organization and title
        if (/(^|\b)(company|organization|organisation)(\b|$)/i.test(t)) return ['organization'];
        if (hasPhrase(t, 'job title') || hasWord(t, 'position') || hasWord(t, 'role')) return ['organization-title'];

        // Honorifics
        if (hasWord(t, 'prefix') || /(mr\.?|mrs\.?|ms\.?|dr\.?)/i.test(t)) return ['honorific-prefix'];
        if (hasWord(t, 'suffix') || /(jr\.?|sr\.?)/i.test(t)) return ['honorific-suffix'];

        // Birthdate
        if (hasPhrase(t, 'date of birth') || hasWord(t, 'dob') || hasWord(t, 'birthday')) return ['bday'];
        if (hasPhrase(t, 'birth month') || hasPhrase(t, 'month of birth')) return ['bday-month'];
        if (hasPhrase(t, 'birth day') || hasPhrase(t, 'day of birth')) return ['bday-day'];
        if (hasPhrase(t, 'birth year') || hasPhrase(t, 'year of birth')) return ['bday-year'];

        // Gender / Sex
        if (hasWord(t, 'gender')) return ['gender', 'sex'];
        if (/(^|\b)sex(\b|$)/i.test(t)) return ['sex'];

        // URLs and IM
        if (hasWord(t, 'website') || hasPhrase(t, 'web site') || hasWord(t, 'url')) return ['url'];
        if (hasPhrase(t, 'instant message') || hasWord(t, 'skype') || hasWord(t, 'telegram')) return ['impp'];

        // Passwords / codes
        if (hasPhrase(t, 'new password') || hasPhrase(t, 'create password')) return ['new-password'];
        if (hasPhrase(t, 'current password') || hasWord(t, 'password')) return ['current-password'];
        if (hasPhrase(t, 'one-time code') || hasPhrase(t, 'verification code') || hasWord(t, 'otp') || hasWord(t, '2fa')) return ['one-time-code'];

        // Credit card fields
        if (hasPhrase(t, 'card number') || hasPhrase(t, 'credit card number') || hasPhrase(t, 'cc number')) return ['cc-number'];
        if (hasPhrase(t, 'cardholder name') || hasPhrase(t, 'name on card') || hasPhrase(t, 'card name')) return ['cc-name'];
        if (hasWord(t, 'expiration') || hasWord(t, 'expiry') || hasPhrase(t, 'exp date')) return ['cc-exp'];
        if (hasPhrase(t, 'exp month')) return ['cc-exp-month'];
        if (hasPhrase(t, 'exp year')) return ['cc-exp-year'];
        if (hasWord(t, 'cvv') || hasWord(t, 'cvc') || hasWord(t, 'csc') || hasPhrase(t, 'security code')) return ['cc-csc'];
        if (hasPhrase(t, 'card type')) return ['cc-type'];

        // Transactions
        if (hasWord(t, 'currency')) return ['transaction-currency'];
        if ((hasWord(t, 'amount') || hasWord(t, 'total')) && (hasWord(t, 'transaction') || hasWord(t, 'payment'))) return ['transaction-amount'];

        // Language / Photo
        if (hasWord(t, 'language')) return ['language'];
        if (hasWord(t, 'photo')) return ['photo'];

        // Not a recognized purpose
        return null;
    };

    let applicable = 0;
    for (const item of d.inputs) {
        const expected = inferExpectedAutocomplete(item.name, item.visualLabel);
        if (!expected || expected.length === 0) {
            continue; // Not applicable for this input
        }
        applicable++;

        const attr = item.autocomplete;
        const val = (attr || '').trim().toLowerCase();

        // If autocomplete is missing or is 'on'/'off', this fails when we expect a specific token
        if (!val || val === 'on' || val === 'off') {
            results.addFail(item.locator);
            continue;
        }

        // Pass if the value matches any of the expected tokens
        if (expected.some(tok => tok.toLowerCase() === val)) {
            results.addPass(item.locator);
        } else {
            results.addFail(item.locator);
        }
    }

    if (applicable === 0) {
        results.addMessage("No inputs with recognizable purpose to check 1.3.5");
        results.forcePass();
    }

    return results;
};

module.exports = testFn;