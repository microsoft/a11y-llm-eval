const FIELD_WRAPPER_SELECTOR = '[class*="field"], [class*="input"], [class*="control"], [class*="item"], [class*="group"]';

// Get all form field wrapper elements within the given scope as Playwright locators
const getAllFormFieldWrappers = async (scope) => {
    return await scope.locator(FIELD_WRAPPER_SELECTOR);
};

module.exports.getAllFormFieldWrappers = getAllFormFieldWrappers;
module.exports.FIELD_WRAPPER_SELECTOR = FIELD_WRAPPER_SELECTOR;