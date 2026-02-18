const FIELD_WRAPPER_SELECTOR = '[class*="field"], [class*="input"], [class*="control"], [class*="item"], [class*="group"]';

// Only treat elements as "field wrappers" if they actually wrap an interactive control.
// This avoids counting helper/error text nodes like `<span class="field-error">...` as wrappers
// simply because their class name contains "field".
//
// Include `contenteditable` because some examples intentionally implement "text inputs" that way;
// those should still be considered fields for role-related assertions.
const CONTROL_SELECTOR = 'input, textarea, select, button, [role="textbox"], [role="button"], [contenteditable]:not([contenteditable="false"]), *:has(> :is(input:not([type=button],[type=submit],[type=reset]), textarea, select))';

// Get all form field wrapper elements within the given scope as Playwright locators
const getAllFormFieldWrappers = async (scope) => {
    const wrappers = scope.locator(FIELD_WRAPPER_SELECTOR);
    return wrappers.filter({ has: scope.locator(CONTROL_SELECTOR) });
};

module.exports.getAllFormFieldWrappers = getAllFormFieldWrappers;
module.exports.FIELD_WRAPPER_SELECTOR = FIELD_WRAPPER_SELECTOR;