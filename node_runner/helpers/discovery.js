const getName = require('./get-name');
const { getVisualLabel } = require('./get-visual-label');
const { getHelperText } = require('./get-helper-text');
const { getAllFormFieldWrappers } = require('./get-form-field-wrapper');

// Perform a single-pass discovery of text inputs and related facts.
// Returns a lightweight cache to be reused across checks to avoid repeated DOM scans.
// shape: {
//   inputs: Array<{
//     locator,
//     name,
//     visualLabel, // { text, source }
//     helperText,  // Array<{ text, source }>
//     visible,
//     tabIndex,    // string|null
//     requiredAttr, // string|null
//     ariaRequired, // string|null
//     programmaticallyRequired: boolean,
//     autocomplete, // string|null
//     placeholder, // string|null
//     ariaPlaceholder, // string|null
//   }>,
//   wrappers: Locator
// }
async function discover(scope) {
  const inputsLocator = scope.getByRole('textbox');
  const count = await inputsLocator.count();

  const facts = [];
  for (let i = 0; i < count; i++) {
    const input = inputsLocator.nth(i);
    const [
      name,
      visualLabel,
      helperText,
      visible,
      tabIndex,
      requiredAttr,
      ariaRequired,
      autocomplete,
      placeholder,
      ariaPlaceholder,
    ] = await Promise.all([
      getName(input),
      getVisualLabel(input),
      getHelperText(input),
      input.isVisible(),
      input.getAttribute('tabindex'),
      input.getAttribute('required'),
      input.getAttribute('aria-required'),
      input.getAttribute('autocomplete'),
      input.getAttribute('placeholder'),
      input.getAttribute('aria-placeholder'),
    ]);

    const programmaticallyRequired = (requiredAttr !== null) || (ariaRequired === 'true');
    facts.push({
      locator: input,
      name,
      visualLabel,
      helperText,
      visible,
      tabIndex,
      requiredAttr,
      ariaRequired,
      programmaticallyRequired,
      autocomplete,
      placeholder,
      ariaPlaceholder,
    });
  }

  // Also discover wrappers so callers that need them can reuse the locator.
  const wrappers = await getAllFormFieldWrappers(scope);

  return { inputs: facts, wrappers };
}

module.exports = { discover };
