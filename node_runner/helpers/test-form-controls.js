const detailedResults = require('./detailed-results');
const getName = require('./get-name');
const { getAccessibilityNodeInfo } = require('./get-accessibility-tree');
const { getVisualLabel, SOURCE_PLACEHOLDER } = require('./get-visual-label');
const { getAllFormFieldWrappers } = require('./get-form-field-wrapper');
const { combineHelperTexts, getHelperText, SOURCE_ARIA_DESCRIBEDBY, SOURCE_ARIA_DESCRIPTION, SOURCE_TITLE, SOURCE_CSS_PLACEHOLDER } = require('./get-helper-text');
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

const getGroupDescriptionLocator = (locator, groupKind) => {
    if (groupKind === 'fieldset') {
        return locator.locator('xpath=ancestor::fieldset[1]').first();
    }

    if (groupKind === 'aria') {
        return locator.locator('xpath=ancestor::*[@role="radiogroup" or @role="group"][1]').first();
    }

    if (groupKind === 'group') {
        return locator.locator('xpath=ancestor::*[@role="group"][1]').first();
    }

    return null;
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
    let applicable = 0;
    const reportedHelperFailures = new Set();

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

    const normalizeForCompare = (value) => (value || '')
        .toString()
        .replace(/\p{P}+/gu, ' ')
        .replace(/[\s\u00A0]+/g, ' ')
        .trim()
        .toLowerCase();

    const normalizeHelpers = (helpers) => {
        const entries = Array.isArray(helpers)
            ? helpers
            : (helpers ? [helpers] : []);

        const unique = new Map();
        for (const helper of entries) {
            const text = helper && helper.text ? String(helper.text).trim() : '';
            if (isTrivialHelperText(text)) {
                continue;
            }
            const source = helper && helper.source ? helper.source : '';
            const key = `${source}:${normalizeForCompare(text)}`;
            if (!unique.has(key)) {
                unique.set(key, { text, source });
            }
        }

        return Array.from(unique.values());
    };

    const hasProgrammaticHelperAssociation = (helpers, options = {}) => {
        if (options.groupHasProgrammaticDescription) {
            return true;
        }

        return helpers.some((helper) => helper && (
            helper.source === SOURCE_ARIA_DESCRIBEDBY
            || helper.source === SOURCE_ARIA_DESCRIPTION
            || helper.source === SOURCE_TITLE
        ));
    };

    const evaluateHelperTarget = (locator, helperEntries, accessibleNames, options = {}) => {
        if (helperEntries.length === 0) {
            return false;
        }

        applicable++;

        const combinedHelperText = combineHelperTexts(helperEntries);
        const helperIncludedInAccessibleName = !!combinedHelperText && accessibleNames.some((name) => {
            const normalizedName = normalizeForCompare(name);
            const normalizedHelper = normalizeForCompare(combinedHelperText);
            return !!normalizedName && !!normalizedHelper && normalizedName.includes(normalizedHelper);
        });

        if (hasProgrammaticHelperAssociation(helperEntries, options) || helperIncludedInAccessibleName) {
            results.addPass(locator);
            return true;
        }

        results.addFail(locator);
        const failureKey = normalizeForCompare(combinedHelperText);
        if (!reportedHelperFailures.has(failureKey)) {
            reportedHelperFailures.add(failureKey);
            results.addMessage("Found `" + combinedHelperText + "`");
        }
        return true;
    };

    const groupedControlType = d && (d.controlType === 'radio' || d.controlType === 'checkbox')
        ? d.controlType
        : null;

    if (groupedControlType && Array.isArray(d.groups) && d.groups.length > 0) {
        const groupedIndexes = new Set();

        for (const group of d.groups) {
            const groupedItems = groupedControlType === 'radio' ? group.radios : group.checkboxes;
            for (const item of groupedItems) {
                groupedIndexes.add(item.domIndex);
            }

            const helperEntries = normalizeHelpers(
                groupedItems.flatMap((item) => Array.isArray(item.helperText)
                    ? item.helperText
                    : (item.helperText ? [item.helperText] : []))
            );

            if (helperEntries.length === 0) {
                continue;
            }

            evaluateHelperTarget(
                groupedItems[0].locator,
                helperEntries,
                [group.groupLabel, ...groupedItems.map((item) => item.name)],
                { groupHasProgrammaticDescription: !!group.groupHasProgrammaticDescription },
            );
        }

        for (const item of d.inputs) {
            if (groupedIndexes.has(item.domIndex)) {
                continue;
            }

            const helperEntries = normalizeHelpers(item.helperText);
            if (helperEntries.length === 0) {
                continue;
            }

            evaluateHelperTarget(item.locator, helperEntries, [item.name]);
        }

        if (applicable === 0) {
            results.addMessage("No meaningful helper text found");
            results.forceNotApplicable();
        }

        return results;
    }

    for (const item of d.inputs) {
        const meaningfulHelpers = normalizeHelpers(item.helperText);

        if (meaningfulHelpers.length === 0) {
            continue; // no meaningful helper text to check
        }

        evaluateHelperTarget(item.locator, meaningfulHelpers, [item.name]);
    }

    if (applicable === 0) {
        results.addMessage("No meaningful helper text found");
        results.forceNotApplicable();
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
        results.forceNotApplicable();
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


const hasAsteriskRequiredIndicator = (labelObj) => {
    if (!labelObj || !labelObj.text) return false;
    const text = labelObj.text.trim();
    return text.startsWith('*') || text.endsWith('*');
};

const hasTextualRequiredIndicator = (rawText) => {
    if (!rawText) return false;
    const t = String(rawText).toLowerCase().trim();

    if (/\(\s*required\s*\)/.test(t)) return true;
    if (/\bmandatory\b/.test(t)) return true;
    if (/\bis required\b/.test(t)) return true;
    if (/\brequired field\b/.test(t)) return true;
    if (/(^|\s)required[\s\.!?)]*$/.test(t)) return true;

    if (/\brequired\s+(length|format|characters?|fields?|value|values|minimum|password|pattern|items?)\b/.test(t)) {
        return false;
    }

    return false;
};

const indicatesRequiredVisually = (labelObj, options = {}) => {
    if (!labelObj) {
        return false;
    }
    if (options.excludePlaceholder && labelObj.source === SOURCE_PLACEHOLDER) {
        return false;
    }
    return hasAsteriskRequiredIndicator(labelObj) || hasTextualRequiredIndicator(labelObj.text);
};

const hasRequiredHelperIndicator = (helpers) => {
    for (const helper of helpers) {
        if (!helper) continue;
        if (hasAsteriskRequiredIndicator(helper) || hasTextualRequiredIndicator(helper.text)) {
            return true;
        }
    }
    return false;
};

const normalizeIndicatorText = (value) => (value || '').toString().replace(/\s+/g, ' ').trim().toLowerCase();

const hasMinimumChoiceHelperIndicator = (helpers, controlType) => {
    const entries = Array.isArray(helpers)
        ? helpers
        : (helpers ? [helpers] : []);

    for (const helper of entries) {
        const text = normalizeIndicatorText(helper && helper.text);
        if (!text) {
            continue;
        }

        const hasOptionLikeTarget = /\b(option|options|choice|choices|item|items|answer|answers|selection|selections)\b/.test(text);

        if (controlType === 'checkbox') {
            if (/\b(choose|select|pick)\s+at\s+least\s+one\b/.test(text)) {
                return true;
            }

            if (/\bat\s+least\s+one\s+(required\s+)?(option|options|choice|choices|item|items|answer|answers|selection|selections)\b/.test(text)) {
                return true;
            }
        }

        if (controlType === 'radio') {
            if (hasOptionLikeTarget && /\b(choose|select|pick)\s+(one|1)\b/.test(text)) {
                return true;
            }

            if (/\bone\s+required\s+(option|choice|item|answer|selection)\b/.test(text)) {
                return true;
            }
        }
    }

    return false;
};

const hasSharedRequiredContextIndicator = async (locator) => {
    return locator.evaluate((element) => {
        const normalizeText = (value) => (value || '').toString().replace(/\s+/g, ' ').trim().toLowerCase();
        const container = element.closest('form, [role="form"], main, body') || document.body;
        const text = normalizeText(container ? container.innerText : '');

        if (!text) {
            return false;
        }

        if (/\ball\s+(questions?|fields?|options?|choices?)\s+(are|marked)\s+required\b/.test(text)) {
            return true;
        }

        if (/\ball\s+required\s+(questions?|fields?|options?|choices?)\b/.test(text)) {
            return true;
        }

        return false;
    });
};

const collectRequiredIndicatorEntries = async (discovery) => {
    const entries = [];
    const groupedControlType = discovery && (discovery.controlType === 'radio' || discovery.controlType === 'checkbox')
        ? discovery.controlType
        : null;
    const isGroupedDiscovery = groupedControlType !== null && Array.isArray(discovery.groups) && discovery.groups.length > 0;

    if (isGroupedDiscovery) {
        for (const group of discovery.groups) {
            const groupedItems = groupedControlType === 'radio' ? group.radios : group.checkboxes;
            const controlLabel = groupedControlType === 'radio' ? 'Radio group' : 'Checkbox group';
            const groupLabelIndicatesRequired = hasAsteriskRequiredIndicator({ text: group.groupLabel }) || hasTextualRequiredIndicator(group.groupLabel);
            const hasMinimumChoiceHelper = groupedItems.some((item) => hasMinimumChoiceHelperIndicator(item.helperText, groupedControlType));

            let itemLevelVisualIndicator = false;
            for (const item of groupedItems) {
                if (indicatesRequiredVisually(item.visualLabel) || hasRequiredHelperIndicator(Array.isArray(item.helperText) ? item.helperText : (item.helperText ? [item.helperText] : []))) {
                    itemLevelVisualIndicator = true;
                    break;
                }
            }

            const sharedContextVisualIndicator = !groupLabelIndicatesRequired && !itemLevelVisualIndicator && groupedItems[0]?.locator
                ? await hasSharedRequiredContextIndicator(groupedItems[0].locator)
                : false;
            const hasProgrammaticIndicator = !group.requiredStateMismatch && (!!group.programmaticallyRequired || groupedItems.some((item) => item.programmaticallyRequired));
            const programmaticNotApplicable = !hasProgrammaticIndicator
                && group.groupKind === 'fieldset'
                && hasMinimumChoiceHelper;

            entries.push({
                locator: groupedItems[0]?.locator,
                hasVisualIndicator: groupLabelIndicatesRequired || itemLevelVisualIndicator || sharedContextVisualIndicator,
                hasProgrammaticIndicator,
                programmaticNotApplicable,
                visualMissingMessage: `${controlLabel} is programmatically required but has no visual required indicator`,
                programmaticMissingMessage: group.requiredStateMismatch
                    ? `${controlLabel} has conflicting native and ARIA required states`
                    : `${controlLabel} appears visually required but has no programmatic required indicator`,
            });
        }

        return entries;
    }

    for (const item of discovery.inputs) {
        const helpers = Array.isArray(item.helperText)
            ? item.helperText
            : (item.helperText ? [item.helperText] : []);
        const localVisualIndicator = indicatesRequiredVisually(item.visualLabel, { excludePlaceholder: true }) || hasRequiredHelperIndicator(helpers);
        const sharedContextVisualIndicator = !localVisualIndicator && item.locator
            ? await hasSharedRequiredContextIndicator(item.locator)
            : false;

        entries.push({
            locator: item.locator,
            hasVisualIndicator: localVisualIndicator || sharedContextVisualIndicator,
            hasProgrammaticIndicator: !item.requiredStateMismatch && !!item.programmaticallyRequired,
            visualMissingMessage: "Input is programmatically required but has no visual required indicator",
            programmaticMissingMessage: item.requiredStateMismatch
                ? "Input has conflicting native and ARIA required states"
                : "Input appears visually required but has no programmatic required indicator",
        });
    }

    return entries;
};

testFn.testRequiredFieldsIndicatedVisually = async (scope, discoveryCache) => {
    let results = new detailedResults();
    const d = discoveryCache || await discover(scope);
    const count = d.inputs.length;

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    const entries = await collectRequiredIndicatorEntries(d);
    let applicable = 0;

    for (const entry of entries) {
        if (!entry.hasProgrammaticIndicator && !entry.hasVisualIndicator) {
            continue;
        }
        applicable++;
        if (entry.hasVisualIndicator) {
            results.addPass(entry.locator);
        } else {
            results.addFail(entry.locator);
            results.addMessage(entry.visualMissingMessage);
        }
    }

    if (applicable === 0) {
        results.addMessage("No programmatically required fields found");
        results.forceNotApplicable();
    }

    return results;
};

testFn.testRequiredFieldsIndicatedProgrammatically = async (scope, discoveryCache) => {
    let results = new detailedResults();
    const d = discoveryCache || await discover(scope);
    const count = d.inputs.length;

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    const entries = await collectRequiredIndicatorEntries(d);
    let applicable = 0;
    let notApplicableGroupedMinimumChoice = 0;

    for (const entry of entries) {
        if (entry.programmaticNotApplicable) {
            notApplicableGroupedMinimumChoice++;
            continue;
        }

        if (!entry.hasVisualIndicator && !entry.hasProgrammaticIndicator) {
            continue;
        }
        applicable++;
        if (entry.hasProgrammaticIndicator) {
            results.addPass(entry.locator);
        } else {
            results.addFail(entry.locator);
            results.addMessage(entry.programmaticMissingMessage);
        }
    }

    if (applicable === 0) {
        if (notApplicableGroupedMinimumChoice > 0) {
            results.addMessage("No applicable programmatic required indicators for native grouped minimum-choice requirements");
        } else {
            results.addMessage("No visually required fields found");
        }
        results.forceNotApplicable();
    }

    return results;
};

// Backward-compatible combined helper retained for callers that still want the previous single assertion.
testFn.testRequiredFieldsIndicated = async (scope, discoveryCache) => {
    let results = new detailedResults();
    const d = discoveryCache || await discover(scope);
    const count = d.inputs.length;

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    const entries = await collectRequiredIndicatorEntries(d);
    let applicable = 0;
    let notApplicableGroupedMinimumChoice = 0;

    for (const entry of entries) {
        if (entry.programmaticNotApplicable) {
            notApplicableGroupedMinimumChoice++;
            continue;
        }

        if (!entry.hasVisualIndicator && !entry.hasProgrammaticIndicator) {
            continue;
        }
        applicable++;
        if (entry.hasVisualIndicator && entry.hasProgrammaticIndicator) {
            results.addPass(entry.locator);
        } else {
            results.addFail(entry.locator);
            if (entry.hasProgrammaticIndicator && !entry.hasVisualIndicator) {
                results.addMessage(entry.visualMissingMessage);
            }
        }
    }

    if (applicable === 0) {
        if (notApplicableGroupedMinimumChoice > 0) {
            results.addMessage("No applicable required-field indicators for native grouped minimum-choice requirements");
        } else {
            results.addMessage("No required fields found");
        }
        results.forceNotApplicable();
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

    // Normalize for comparison:
    // - replace all Unicode punctuation with spaces
    // - collapse whitespace (including NBSP)
    // - trim + lowercase
    const normalizeForCompare = (s) => (s || '')
        .toString()
        .replace(/\p{P}+/gu, ' ')
        .replace(/[\s\u00A0]+/g, ' ')
        .trim()
        .toLowerCase();

    // Remove common non-essential "required" indicators from visible labels only.
    const stripRequiredIndicators = (s) => (s || '')
        .toString()
        .replace(/\(\s*required\s*\)/gi, '')
        .replace(/\brequired\b/gi, '');

    // Only applies when there is a visible text label (not placeholder-only)
    let applicable = 0;
    for (const item of d.inputs) {
        const vl = item.visualLabel;
        if (!vl || !vl.text || !vl.text.trim()) {
            continue; // no visible text label
        }
        applicable++;

        const labelNorm = normalizeForCompare(stripRequiredIndicators(vl.text));
        const nameNorm = normalizeForCompare(item.name || '');

        // Accessible name should contain the visible label text in the same order
        if (labelNorm && nameNorm.includes(labelNorm)) {
            results.addPass(item.locator);
        } else {
            results.addFail(item.locator);
        }
    }

    if (applicable === 0) {
        results.addMessage("No inputs with visible text labels applicable to 2.5.3");
        results.forceNotApplicable();
    }

    return results;
}

// Expose discovery so callers can prime and pass a cache
testFn.discover = discover;
testFn.discoverTextInputs = discover;

testFn.discoverRadios = async (scope) => {
    const radioLocator = scope.locator('input[type="radio"], [role="radio"]');
    const count = await radioLocator.count();
    const inputs = [];
    const groupsByKey = new Map();

    for (let index = 0; index < count; index++) {
        const locator = radioLocator.nth(index);
        const [name, rawVisualLabel, rawHelperText, visible, meta] = await Promise.all([
            getName(locator),
            getVisualLabel(locator),
            getHelperText(locator),
            locator.isVisible(),
            locator.evaluate((radio, args) => {
        const { idx } = args;
        const isVisible = (node) => window.axe.commons.dom.isVisible(node, false, true);
        const normalizeText = (value) => (value || '').toString().replace(/\s+/g, ' ').trim();
        const parseAriaBoolean = (value) => {
            if (value === 'true') {
                return true;
            }
            if (value === 'false') {
                return false;
            }
            return null;
        };

        const getNodePath = (element) => {
            if (!element) {
                return '';
            }

            const segments = [];
            let current = element;

            while (current && current.nodeType === Node.ELEMENT_NODE) {
                let segment = current.tagName.toLowerCase();

                if (current.id) {
                    segment += `#${current.id}`;
                    segments.unshift(segment);
                    break;
                }

                let siblingIndex = 1;
                let sibling = current;
                while ((sibling = sibling.previousElementSibling) !== null) {
                    if (sibling.tagName === current.tagName) {
                        siblingIndex += 1;
                    }
                }

                segment += `:nth-of-type(${siblingIndex})`;
                segments.unshift(segment);
                current = current.parentElement;
            }

            return segments.join(' > ');
        };

        const getLegendText = (fieldset) => {
            if (!fieldset) {
                return '';
            }

            const legend = Array.from(fieldset.children).find((child) => child.tagName === 'LEGEND');
            return normalizeText(legend ? legend.textContent : '');
        };

        const ariaGroups = Array.from(document.querySelectorAll('[role="radiogroup"], [role="group"]'));
        const fieldsets = Array.from(document.querySelectorAll('fieldset'));
        const forms = Array.from(document.querySelectorAll('form'));
        const nativeFieldset = radio.closest('fieldset');
        const ariaGroup = radio.closest('[role="radiogroup"], [role="group"]');
        const isNativeRadio = radio.matches('input[type="radio"]');
        const ariaGroupRole = ariaGroup ? ariaGroup.getAttribute('role') : '';
        const requiredAttr = radio.getAttribute('required');
        const ariaRequired = radio.getAttribute('aria-required');
        const ariaDisabled = radio.getAttribute('aria-disabled');
        const ariaChecked = radio.getAttribute('aria-checked');
        const nativeDisabled = isNativeRadio ? radio.disabled : radio.hasAttribute('disabled');
        const nativeChecked = isNativeRadio ? radio.checked : radio.hasAttribute('checked');
        const nativeRequired = requiredAttr !== null;
        const ariaDisabledState = parseAriaBoolean(ariaDisabled);
        const ariaCheckedState = parseAriaBoolean(ariaChecked);
        const ariaRequiredState = parseAriaBoolean(ariaRequired);
        const disabled = isNativeRadio
            ? nativeDisabled
            : ariaDisabledState === true || nativeDisabled;
        const checked = isNativeRadio
            ? nativeChecked
            : ariaCheckedState === true || nativeChecked;
        const controlText = normalizeText(radio.innerText || radio.textContent || '');
        const groupProgrammaticallyRequired = ariaGroupRole === 'radiogroup' && ariaGroup && ariaGroup.getAttribute('aria-required') === 'true';
        const checkedStateDefined = isNativeRadio || ariaCheckedState !== null;
        const checkedStateMismatch = isNativeRadio && ariaCheckedState !== null && ariaCheckedState !== nativeChecked;
        const disabledStateMismatch = isNativeRadio && ariaDisabledState !== null && ariaDisabledState !== nativeDisabled;
        const requiredStateMismatch = isNativeRadio && ariaRequiredState !== null && ariaRequiredState !== nativeRequired;

        const stateConsistencyIssues = [];
        if (checkedStateMismatch) {
            stateConsistencyIssues.push('checked');
        }
        if (disabledStateMismatch) {
            stateConsistencyIssues.push('disabled');
        }
        if (requiredStateMismatch) {
            stateConsistencyIssues.push('required');
        }

        let groupKey;
        let groupKind;
        let groupLabel = '';
                let groupHasProgrammaticDescription = false;

        if (ariaGroup) {
            const groupIndex = ariaGroups.indexOf(ariaGroup);
            groupKey = `aria:${groupIndex}:${getNodePath(ariaGroup)}`;
            groupKind = 'aria';
        } else if (nativeFieldset) {
            const fieldsetIndex = fieldsets.indexOf(nativeFieldset);
            groupKey = `fieldset:${fieldsetIndex}:${getNodePath(nativeFieldset)}`;
            groupKind = 'fieldset';
            groupLabel = getLegendText(nativeFieldset);
        } else if (isNativeRadio) {
            const form = radio.closest('form');
            const formIndex = form ? forms.indexOf(form) : -1;
            const groupName = radio.getAttribute('name') || `unnamed-${idx}`;
            groupKey = `native-fallback:${formIndex}:${groupName}`;
            groupKind = 'native-fallback';
        } else {
            const parent = radio.parentElement;
            groupKey = `aria-fallback:${getNodePath(parent) || `orphan-${idx}`}`;
            groupKind = 'aria-fallback';
        }

        return {
            domIndex: idx,
            groupKey,
            groupKind,
            groupLabel,
            groupHasProgrammaticDescription,
            disabled,
            checked,
            checkedStateDefined,
            checkedStateMismatch,
            disabledStateMismatch,
            requiredStateMismatch,
            hasNativeAriaStateMismatch: stateConsistencyIssues.length > 0,
            nativeAriaStateMismatchCount: stateConsistencyIssues.length,
            nativeAriaStateMismatchDetails: stateConsistencyIssues,
            tabIndex: radio.tabIndex,
            programmaticallyRequired: nativeRequired || ariaRequiredState === true,
            groupProgrammaticallyRequired,
            controlText,
        };
            }, { idx: index }),
        ]);

        const helperText = Array.isArray(rawHelperText)
            ? rawHelperText
            : (rawHelperText ? [rawHelperText] : []);
        let groupHasProgrammaticDescription = false;
        let groupLabel = meta.groupLabel;
        const groupLocator = getGroupDescriptionLocator(locator, meta.groupKind);
        let visualLabel = rawVisualLabel;

        if (groupLocator && await groupLocator.count()) {
            const groupAccessibilityNode = await getAccessibilityNodeInfo(groupLocator);
            groupLabel = groupAccessibilityNode.name || groupLabel;
            groupHasProgrammaticDescription = !!groupAccessibilityNode.description;
        }

        if ((!visualLabel || !visualLabel.text || !visualLabel.text.trim()) && meta.controlText) {
            visualLabel = { text: meta.controlText, source: 'CONTROL_TEXT' };
        }

        const item = {
            locator,
            domIndex: meta.domIndex,
            name,
            visualLabel,
            helperText,
            visible,
            disabled: meta.disabled,
            tabIndex: meta.tabIndex,
            checked: meta.checked,
            checkedStateDefined: meta.checkedStateDefined,
            checkedStateMismatch: meta.checkedStateMismatch,
            disabledStateMismatch: meta.disabledStateMismatch,
            requiredStateMismatch: meta.requiredStateMismatch,
            hasNativeAriaStateMismatch: meta.hasNativeAriaStateMismatch,
            nativeAriaStateMismatchCount: meta.nativeAriaStateMismatchCount,
            nativeAriaStateMismatchDetails: meta.nativeAriaStateMismatchDetails,
            programmaticallyRequired: meta.programmaticallyRequired,
            groupKey: meta.groupKey,
            groupKind: meta.groupKind,
            groupLabel,
            groupHasProgrammaticDescription,
        };

        inputs.push(item);

        if (!groupsByKey.has(meta.groupKey)) {
            groupsByKey.set(meta.groupKey, {
                groupKey: meta.groupKey,
                groupKind: meta.groupKind,
                groupLabel,
                programmaticallyRequired: meta.groupProgrammaticallyRequired,
                groupHasProgrammaticDescription,
                hasNativeAriaStateMismatch: false,
                nativeAriaStateMismatchCount: 0,
                nativeAriaStateMismatchDetails: [],
                requiredStateMismatch: false,
                radios: [],
            });
        }

        const group = groupsByKey.get(meta.groupKey);
        group.radios.push(item);
        if (meta.hasNativeAriaStateMismatch) {
            group.hasNativeAriaStateMismatch = true;
            group.nativeAriaStateMismatchCount += meta.nativeAriaStateMismatchCount;
            group.nativeAriaStateMismatchDetails = group.nativeAriaStateMismatchDetails.concat(meta.nativeAriaStateMismatchDetails);
        }
        if (meta.requiredStateMismatch) {
            group.requiredStateMismatch = true;
        }
    }

    const normalizeText = (value) => (value || '').toString().replace(/\s+/g, ' ').trim().toLowerCase();
    const groups = Array.from(groupsByKey.values());

    for (const group of groups) {
        const groupLabel = normalizeText(group.groupLabel);
        const radioLabels = new Set(
            group.radios
                .map((radio) => normalizeText((radio.visualLabel && radio.visualLabel.text) || radio.name))
                .filter(Boolean)
        );

        for (const radio of group.radios) {
            radio.helperText = radio.helperText.filter((helper) => {
                const text = normalizeText(helper && helper.text);
                if (!text) {
                    return false;
                }
                if (text === groupLabel) {
                    return false;
                }
                if (radioLabels.has(text)) {
                    return false;
                }
                return true;
            });
        }
    }

    return { inputs, groups, controlType: 'radio' };
};

testFn.discoverRadioGroups = async (scope, discoveryCache) => {
    const discoveryCacheObj = discoveryCache && discoveryCache.groups ? discoveryCache : await testFn.discoverRadios(scope);
    return discoveryCacheObj.groups;
};

testFn.getCheckedRadioIndexes = (group) => {
    return group.radios.filter((radio) => radio.checked).map((radio) => radio.domIndex);
};

testFn.discoverCheckboxes = async (scope) => {
    const checkboxLocator = scope.locator('input[type="checkbox"], [role="checkbox"]');
    const count = await checkboxLocator.count();
    const inputs = [];
    const groupsByKey = new Map();

    for (let index = 0; index < count; index++) {
        const locator = checkboxLocator.nth(index);
        const [name, rawVisualLabel, rawHelperText, visible, meta] = await Promise.all([
            getName(locator),
            getVisualLabel(locator),
            getHelperText(locator),
            locator.isVisible(),
            locator.evaluate((checkbox, args) => {
                const { idx } = args;
                const normalizeText = (value) => (value || '').toString().replace(/\s+/g, ' ').trim();
                const parseAriaBoolean = (value) => {
                    if (value === 'true') {
                        return true;
                    }
                    if (value === 'false') {
                        return false;
                    }
                    return null;
                };
                const parseAriaCheckedState = (value) => {
                    if (value === 'true' || value === true) {
                        return 'true';
                    }
                    if (value === 'false' || value === false) {
                        return 'false';
                    }
                    if (value === 'mixed') {
                        return 'mixed';
                    }
                    return null;
                };

                const getNodePath = (element) => {
                    if (!element) {
                        return '';
                    }

                    const segments = [];
                    let current = element;

                    while (current && current.nodeType === Node.ELEMENT_NODE) {
                        let segment = current.tagName.toLowerCase();

                        if (current.id) {
                            segment += `#${current.id}`;
                            segments.unshift(segment);
                            break;
                        }

                        let siblingIndex = 1;
                        let sibling = current;
                        while ((sibling = sibling.previousElementSibling) !== null) {
                            if (sibling.tagName === current.tagName) {
                                siblingIndex += 1;
                            }
                        }

                        segment += `:nth-of-type(${siblingIndex})`;
                        segments.unshift(segment);
                        current = current.parentElement;
                    }

                    return segments.join(' > ');
                };

                const getLegendText = (fieldset) => {
                    if (!fieldset) {
                        return '';
                    }

                    const legend = Array.from(fieldset.children).find((child) => child.tagName === 'LEGEND');
                    return normalizeText(legend ? legend.textContent : '');
                };

                const groupContainers = Array.from(document.querySelectorAll('fieldset, [role="group"]'));
                const fieldsets = Array.from(document.querySelectorAll('fieldset'));
                const isNativeCheckbox = checkbox.matches('input[type="checkbox"]');
                const groupContainer = checkbox.closest('fieldset, [role="group"]');
                const requiredAttr = checkbox.getAttribute('required');
                const ariaRequired = checkbox.getAttribute('aria-required');
                const ariaDisabled = checkbox.getAttribute('aria-disabled');
                const ariaChecked = checkbox.getAttribute('aria-checked');
                const nativeDisabled = isNativeCheckbox ? checkbox.disabled : checkbox.hasAttribute('disabled');
                const nativeChecked = isNativeCheckbox ? checkbox.checked : checkbox.hasAttribute('checked');
                const nativeIndeterminate = isNativeCheckbox ? checkbox.indeterminate === true : false;
                const nativeRequired = requiredAttr !== null;
                const ariaDisabledState = parseAriaBoolean(ariaDisabled);
                const ariaCheckedState = parseAriaCheckedState(ariaChecked);
                const ariaRequiredState = parseAriaBoolean(ariaRequired);
                const disabled = isNativeCheckbox
                    ? nativeDisabled
                    : ariaDisabledState === true || nativeDisabled;
                const checked = isNativeCheckbox
                    ? nativeChecked
                    : ariaCheckedState === 'true' || nativeChecked;
                const controlText = normalizeText(checkbox.innerText || checkbox.textContent || '');
                const nativeCheckedState = nativeIndeterminate ? 'mixed' : (nativeChecked ? 'true' : 'false');
                const checkedStateDefined = isNativeCheckbox || ariaCheckedState !== null;
                const checkedStateMismatch = isNativeCheckbox && ariaCheckedState !== null && ariaCheckedState !== nativeCheckedState;
                const disabledStateMismatch = isNativeCheckbox && ariaDisabledState !== null && ariaDisabledState !== nativeDisabled;
                const requiredStateMismatch = isNativeCheckbox && ariaRequiredState !== null && ariaRequiredState !== nativeRequired;

                const stateConsistencyIssues = [];
                if (checkedStateMismatch) {
                    stateConsistencyIssues.push('checked');
                }
                if (disabledStateMismatch) {
                    stateConsistencyIssues.push('disabled');
                }
                if (requiredStateMismatch) {
                    stateConsistencyIssues.push('required');
                }

                let groupKey = null;
                let groupKind = '';
                let groupLabel = '';
                let groupProgrammaticallyRequired = false;
                let groupHasProgrammaticDescription = false;

                if (groupContainer) {
                    if (groupContainer.tagName === 'FIELDSET') {
                        groupKey = `fieldset:${fieldsets.indexOf(groupContainer)}:${getNodePath(groupContainer)}`;
                        groupKind = 'fieldset';
                        groupLabel = getLegendText(groupContainer);
                    } else {
                        groupKey = `group:${groupContainers.indexOf(groupContainer)}:${getNodePath(groupContainer)}`;
                        groupKind = 'group';
                        if (groupContainer.getAttribute('aria-required') === 'true') {
                            groupProgrammaticallyRequired = true;
                        }
                    }
                }

                return {
                    domIndex: idx,
                    groupKey,
                    groupKind,
                    groupLabel,
                    groupProgrammaticallyRequired,
                    disabled,
                    checked,
                    checkedStateDefined,
                    checkedStateMismatch,
                    disabledStateMismatch,
                    requiredStateMismatch,
                    hasNativeAriaStateMismatch: stateConsistencyIssues.length > 0,
                    nativeAriaStateMismatchCount: stateConsistencyIssues.length,
                    nativeAriaStateMismatchDetails: stateConsistencyIssues,
                    tabIndex: checkbox.tabIndex,
                    programmaticallyRequired: nativeRequired || ariaRequiredState === true,
                    controlText,
                };
            }, { idx: index }),
        ]);

        const helperText = Array.isArray(rawHelperText)
            ? rawHelperText
            : (rawHelperText ? [rawHelperText] : []);
        let groupHasProgrammaticDescription = false;
        let groupLabel = meta.groupLabel;
        const groupLocator = getGroupDescriptionLocator(locator, meta.groupKind);
        let visualLabel = rawVisualLabel;

        if (groupLocator && await groupLocator.count()) {
            const groupAccessibilityNode = await getAccessibilityNodeInfo(groupLocator);
            groupLabel = groupAccessibilityNode.name || groupLabel;
            groupHasProgrammaticDescription = !!groupAccessibilityNode.description;
        }

        if ((!visualLabel || !visualLabel.text || !visualLabel.text.trim()) && meta.controlText) {
            visualLabel = { text: meta.controlText, source: 'CONTROL_TEXT' };
        }

        const item = {
            locator,
            domIndex: meta.domIndex,
            name,
            visualLabel,
            helperText,
            visible,
            disabled: meta.disabled,
            tabIndex: meta.tabIndex,
            checked: meta.checked,
            checkedStateDefined: meta.checkedStateDefined,
            checkedStateMismatch: meta.checkedStateMismatch,
            disabledStateMismatch: meta.disabledStateMismatch,
            requiredStateMismatch: meta.requiredStateMismatch,
            hasNativeAriaStateMismatch: meta.hasNativeAriaStateMismatch,
            nativeAriaStateMismatchCount: meta.nativeAriaStateMismatchCount,
            nativeAriaStateMismatchDetails: meta.nativeAriaStateMismatchDetails,
            programmaticallyRequired: meta.programmaticallyRequired,
            groupKey: meta.groupKey,
            groupKind: meta.groupKind,
            groupLabel,
            groupHasProgrammaticDescription,
        };

        inputs.push(item);

        if (meta.groupKey) {
            if (!groupsByKey.has(meta.groupKey)) {
                groupsByKey.set(meta.groupKey, {
                    groupKey: meta.groupKey,
                    groupKind: meta.groupKind,
                    groupLabel,
                    programmaticallyRequired: meta.groupProgrammaticallyRequired,
                    groupHasProgrammaticDescription,
                    hasNativeAriaStateMismatch: false,
                    nativeAriaStateMismatchCount: 0,
                    nativeAriaStateMismatchDetails: [],
                    requiredStateMismatch: false,
                    checkboxes: [],
                });
            }

            const group = groupsByKey.get(meta.groupKey);
            group.checkboxes.push(item);
            if (meta.hasNativeAriaStateMismatch) {
                group.hasNativeAriaStateMismatch = true;
                group.nativeAriaStateMismatchCount += meta.nativeAriaStateMismatchCount;
                group.nativeAriaStateMismatchDetails = group.nativeAriaStateMismatchDetails.concat(meta.nativeAriaStateMismatchDetails);
            }
            if (meta.requiredStateMismatch) {
                group.requiredStateMismatch = true;
            }
        }
    }

    const normalizeText = (value) => (value || '').toString().replace(/\s+/g, ' ').trim().toLowerCase();
    const groups = Array.from(groupsByKey.values());

    for (const group of groups) {
        const groupLabel = normalizeText(group.groupLabel);
        const checkboxLabels = new Set(
            group.checkboxes
                .map((checkbox) => normalizeText((checkbox.visualLabel && checkbox.visualLabel.text) || checkbox.name))
                .filter(Boolean)
        );

        for (const checkbox of group.checkboxes) {
            checkbox.helperText = checkbox.helperText.filter((helper) => {
                const text = normalizeText(helper && helper.text);
                if (!text) {
                    return false;
                }
                if (text === groupLabel) {
                    return false;
                }
                if (checkboxLabels.has(text)) {
                    return false;
                }
                if (text === 'continue' || text === 'submit') {
                    return false;
                }
                return true;
            });
        }
    }

    return { inputs, groups, controlType: 'checkbox' };
};

testFn.discoverCheckboxGroups = async (scope, discoveryCache) => {
    const discoveryCacheObj = discoveryCache && discoveryCache.groups ? discoveryCache : await testFn.discoverCheckboxes(scope);
    return discoveryCacheObj.groups;
};

testFn.getCheckedCheckboxIndexes = (group) => {
    return group.checkboxes.filter((checkbox) => checkbox.checked).map((checkbox) => checkbox.domIndex);
};

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
        results.forceNotApplicable();
    }

    return results;
};

module.exports = testFn;