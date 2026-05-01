---
description: "Accessibility coding rules: WCAG 2.2 AA conformance, semantic structure, keyboard support, focus management. Apply when writing or modifying UI code."
applyTo: "**"
---

# Accessibility instructions (standard)

Conform to [WCAG 2.2 Level AA](https://www.w3.org/TR/WCAG22/). Do not claim output is "fully accessible" — state what was addressed and any known limitations.

## Implementation priority

Use the first option that fits:

1. Existing accessible component in the project / design system.
2. A component library already in use.
3. Native platform semantics (`<button>`, `<a href>`, `<input>`, `<label>`, `<fieldset>`/`<legend>`, `<dialog>`, `<nav>`, `<main>`, `<h1>`–`<h6>`).
4. Native element + minimum necessary ARIA.
5. Fully custom ARIA widget — only when nothing above fits, and only with complete APG keyboard, focus, and state behavior.

No ARIA is better than bad ARIA. Don't duplicate native semantics (no `role="button"` on `<button>`). Don't use `role="menu"` for site navigation.

## Structure

- Use landmark elements (`<header>`, `<nav>`, `<main>`, `<footer>`). Exactly one `<main>`. Give duplicated landmarks unique accessible names.
- One `<h1>` per view, typically first heading in `<main>`. Don't skip heading levels.
- Set a descriptive `<title>`.
- **Web pages only:** Provide a "Skip to main content" link as the first focusable element.

## Name, role, value

- Every interactive element exposes an accurate accessible name. Role matches purpose. Dynamic states (pressed, expanded, selected, checked, disabled, invalid) stay in sync with visuals.
- The accessible name MUST contain the visible label text. When multiple controls share a label (e.g. many "Remove" buttons), add context: `aria-label="Remove item: Socks"`.

## Keyboard and focus

- All functionality can be achieved by both mouse an keyboard; tab order matches reading/visual order.
- Focus is always visible — do not remove focus outlines without an equal-or-better replacement.
- No keyboard traps outside modals. Escape closes overlays.
- Static content MUST NOT be sequentially focusable. Use `tabindex="-1"` only for programmatic focus targets.
- Content hidden from AT (`aria-hidden="true"`) MUST NOT be focusable.
- Dialogs move focus in and restore it on close.
- Composite widgets (tabs, listbox, menu, grid): one tab stop total; arrow keys move focus internally via roving `tabindex` or `aria-activedescendant`.

## Forms

- Every form field has a visual and programmatic label (`<label for>` or wrapping `<label>`). Never rely on placeholder alone.
- Associate help/error text via `aria-describedby`.
- Group related options (checkboxes, radios) with `<fieldset>` + `<legend>`.
- Required fields: visible indicator (e.g., `*`) AND `required` / `aria-required="true"`. Never color alone. This is a MUST when the form contains both required and optional fields.
- Invalid fields: `aria-invalid="true"`; remove when corrected. Error messages explain how to fix.
- On submit with invalid input, focus the first invalid control. Don't disable submit solely to prevent submission.

## Contrast and color

- Text contrast ≥ 4.5:1 (≥ 3:1 for large text: 24px regular or 18.66px bold).
- Focus indicators and key control boundaries ≥ 3:1 vs adjacent colors.
- Never use color as the only cue for meaning (error, success, required, selected).
- Use design tokens / CSS custom properties. Avoid `opacity`, `rgba`, `hsla` on text and essential affordances — contrast becomes background-dependent.
- Ensure contrast in all states: default, hover, active, focus, visited, disabled.

## Forced colors / OS settings

- Never override OS high-contrast, reduced-motion, or color-scheme preferences without good reason.
- Do not use `forced-color-adjust: none` without good reason (e.g., data-viz where color needs to remain the same).
- In `@media (forced-colors: active)`, use system color keywords (`ButtonText`, `ButtonBorder`, `CanvasText`, `Canvas`) — never fixed hex/RGB.
- Use `currentColor` for SVG `fill`/`stroke` so icons inherit the foreground.
- If relying on `box-shadow` for focus, add a transparent `outline` so focus renders in forced colors.

## Reflow (SC 1.4.10)

- Content MUST be able to 320 CSS pixels wide without two-dimensional scrolling for multi-line text.
- For multi-column layouts that are not necessary to convey meaning or important to the UX of the interface, content stacks; text wraps; controls remain operable.
- Use fluid `flex`/`grid`. Set `max-width: 100%` on media, `min-width: 0` on flex/grid children, `overflow-wrap: anywhere` for long strings.
- Exception: inherently 2D components (large tables, maps, charts, media, interfaces with toolbars or interfaces that require 2D layout) may scroll horizontally at component level; the surrounding view still reflows.

## Graphics

- Informative `<img>` → meaningful `alt`. Decorative `<img>` → `alt=""`.
- Informative `<svg>` → `role="img"` with `aria-label` / `aria-labelledby`. Decorative SVG/graphics → `aria-hidden="true"`.

## Navigation

- Use `<nav>` with lists and links — not `role="menu"` / `role="menubar"`.
- Expandable navigation: toggle uses `button[aria-expanded]`. Escape MAY close sub-navigations.

## Tables and grids

- Static tabular data: `<table>` with `<th>` for column/row headers.
- Use `role="grid"` only for genuinely interactive tabular UIs, with proper row/cell nesting and arrow-key navigation.

## Status messages

- Announce dynamic updates (loading, success, failure, error, validation summaries) via `aria-live="polite"` or `aria-live="assertive"`.

## Final verification

Before finalizing, verify: landmarks + one `<h1>`; keyboard operability with visible focus and no traps; visible labels included in accessible names; form labels + required + error association + focus-first-invalid; contrast thresholds; forced-colors adaptation; reflow at 320px; image alternatives; table header associations.