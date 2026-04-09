const CONTROL_SELECTOR = 'input, textarea, select, button, [role="textbox"], [role="button"], [contenteditable]:not([contenteditable="false"])';
const FIELD_SELECTOR = CONTROL_SELECTOR.replace('button, ','').replace('input','input:not([type="submit"], [type="reset"], [type="button"])');
const PRIMARY_SEMANTIC_FIELD_WRAPPER_SELECTOR = '[class*="field"], [class*="input"], [class*="control"]';
const SECONDARY_SEMANTIC_FIELD_WRAPPER_SELECTOR = '[class*="item"], [class*="group"]';
const FALLBACK_FIELD_WRAPPER_SELECTOR = `*:has(> :is(${FIELD_SELECTOR}))`;
const FIELD_WRAPPER_SELECTOR = `${PRIMARY_SEMANTIC_FIELD_WRAPPER_SELECTOR}, ${SECONDARY_SEMANTIC_FIELD_WRAPPER_SELECTOR}, ${FALLBACK_FIELD_WRAPPER_SELECTOR}`;

// Get all form field wrapper elements within the given scope as Playwright locators
const getAllFormFieldWrappers = async (scope) => {
    const wrappers = scope.locator(FIELD_WRAPPER_SELECTOR);
    return wrappers.filter({ has: scope.locator(CONTROL_SELECTOR) });
};

module.exports.getAllFormFieldWrappers = getAllFormFieldWrappers;
module.exports.FIELD_WRAPPER_SELECTOR = FIELD_WRAPPER_SELECTOR;
module.exports.PRIMARY_SEMANTIC_FIELD_WRAPPER_SELECTOR = PRIMARY_SEMANTIC_FIELD_WRAPPER_SELECTOR;
module.exports.SECONDARY_SEMANTIC_FIELD_WRAPPER_SELECTOR = SECONDARY_SEMANTIC_FIELD_WRAPPER_SELECTOR;
module.exports.FALLBACK_FIELD_WRAPPER_SELECTOR = FALLBACK_FIELD_WRAPPER_SELECTOR;