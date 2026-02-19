const CONTROL_SELECTOR = 'input, textarea, select, button, [role="textbox"], [role="button"], [contenteditable]:not([contenteditable="false"])';
const FIELD_SELECTOR = CONTROL_SELECTOR.replace('button, ','').replace('input','input:not([type="submit"], [type="reset"], [type="button"])');
const FIELD_WRAPPER_SELECTOR = `[class*="field"], [class*="input"], [class*="control"], [class*="item"], [class*="group"], *:has(> :is(${FIELD_SELECTOR}))`;

// Get all form field wrapper elements within the given scope as Playwright locators
const getAllFormFieldWrappers = async (scope) => {
    const wrappers = scope.locator(FIELD_WRAPPER_SELECTOR);
    return wrappers.filter({ has: scope.locator(CONTROL_SELECTOR) });
};

module.exports.getAllFormFieldWrappers = getAllFormFieldWrappers;
module.exports.FIELD_WRAPPER_SELECTOR = FIELD_WRAPPER_SELECTOR;