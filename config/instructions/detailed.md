---
description: "Accessibility coding rules: WCAG 2.2 AA conformance, keyboard operability, semantic structure, focus management. Apply when writing or modifying any UI code. Not applicable to non-UI code (configuration, build scripts, pure logic)."
applyTo: "**"
---

# Accessibility instructions (detailed)

You are an expert in accessibility with deep software engineering expertise.

## Non-negotiables (MUST)

- Conform to [WCAG 2.2 Level AA](https://www.w3.org/TR/WCAG22/).
- Go beyond minimum conformance when it meaningfully improves usability.
- If the project uses a UI component library, you MUST use the component patterns as defined by the library. Do not recreate patterns.
  - If unsure, find an existing usage in the project and follow the same patterns.
  - Ensure the resulting UI still has correct accessible name/role/value, keyboard behavior, focus management, visible labels and meets at least minimum contrast requirements.
- If there is no component library (or a needed component does not exist), prefer platform-native semantics over custom accessibility overrides.
  - **Web:** Prefer native HTML elements/attributes over ARIA. Use ARIA only when necessary (do not add ARIA to native elements when the native semantics already work).
- Ensure correct accessible **name, role, value, states, and properties**.
- All interactive elements are keyboard operable, with clearly visible focus, and no keyboard traps.
- Do not claim the output is “fully accessible”.

## Inclusive language (MUST)

- Use respectful, inclusive, people-first language in any user-facing text.
- Avoid stereotypes or assumptions about ability, cognition, or experience.

## Cognitive load (SHOULD)

- Prefer plain language.
- Use consistent layout structure with identifiable regions.
- Keep navigation order consistent.
- Keep the interface clean and simple (avoid unnecessary distractions).

## Structure and semantics

### View structure (MUST)

- Use semantic regions/landmarks to define the structure of the view.
  - **Web:** Use landmark elements (`<header>`, `<nav>`, `<main>`, `<footer>`).
- Use headings to introduce new sections of content; avoid skipping heading levels.
- Prefer one top-level heading for the view's topic.
  - **Web:** Use one `<h1>`, generally the first heading within the `<main>` landmark.

### View/screen title (SHOULD)

- Every view or screen should have a descriptive, unique title.
  - **Web:** Set a descriptive `<title>`. Prefer: "Unique page - section - site".

## Keyboard and focus

### Core rules (MUST)

- All interactive elements are keyboard operable.
- Tab order follows reading order and is predictable.
- Focus is always visible.
- Hidden content must not be focusable.
  - **Web:** Use `hidden`, `display:none`, or `visibility:hidden`.
- Content hidden from assistive technology, and all of its descendants, must not be focusable.
  - **Web:** This includes content with `aria-hidden="true"`.
- Static content MUST NOT be sequentially focusable.
  - Elements that need programmatic (but not sequential) focus may be made focusable without appearing in the tab order.
  - **Web:** Use `tabindex="-1"`.

### Skip link / bypass blocks (MUST for web pages)

Applies only to **web pages served in a browser** where users navigate between pages with repeated navigation blocks. Does not apply to single-page applications, desktop applications using web technologies (e.g., Electron, Tauri), or views that do not repeat navigation across page loads.

```html
<header>
  <a href="#maincontent" class="sr-only">Skip to main content</a>
  <!-- header content -->
</header>
<nav>
  <!-- navigation -->
</nav>
<main id="maincontent" tabindex="-1">
  <h1><!-- page title --></h1>
  <!-- content -->
</main>
```

```css
.sr-only:not(:focus):not(:active) {
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  height: 1px;
  overflow: hidden;
  position: absolute;
  white-space: nowrap;
  width: 1px;
}
```

### Composite widgets (SHOULD)

If a component uses arrow-key navigation within itself (tabs, listbox, menu-like UI, grid/date picker):

- Provide one sequential focus stop for the composite container or one child.
- Arrow keys move focus between items within the composite.
- Manage internal focus so that exactly one item is focusable at a time; all others are removed from the tab order.

**Web implementation:**

Roving tabindex (SHOULD):

- Exactly one focusable item has `tabindex="0"`; all others are `-1`.
- Arrow keys move focus by swapping tabindex and calling `.focus()`.

`aria-activedescendant` (SHOULD):

- Container is implicitly focusable or has `tabindex="0"` and `aria-activedescendant="IDREF"`.
- Arrow keys update `aria-activedescendant`.

## Low vision and contrast (MUST)

### Contrast requirements (MUST)

- Text contrast: at least 4.5:1 (large text: 3:1).
  - Large text is at least 24px regular or 18.66px bold.
- Focus indicators and key control boundaries: at least 3:1 vs adjacent colors.
- Do not rely on color alone to convey information (error/success/required/selected). Provide text and/or icons with accessible names.

### Color generation rules (MUST)

- Do not invent arbitrary colors.
  - Use project-approved design tokens.
  - If no palette exists, define a small token palette and only use those tokens.
- Avoid alpha/transparency for text and key UI affordances because contrast becomes background-dependent and often fails.
  - **Web:** Avoid `opacity`, `rgba`, `hsla` for text and essential UI element colors.
- Ensure contrast for all interactive states: default, hover, active, focus, visited (links), and disabled.

### Safe defaults when unsure (SHOULD)

- Prefer very dark text on very light backgrounds, or the reverse.
- Avoid mid-gray text on white; muted text should still meet 4.5:1.

### Tokenized palette contract (SHOULD)

- Define and use named design tokens for all UI colors (e.g., background, text, muted-text, link, border, focus, danger, success).
- Only assign UI colors via these tokens (avoid scattered hard-coded color values).
  - **Web:** Use CSS custom properties like `--color-bg`, `--color-text`, etc. Avoid inline hex values.

### Verification (MUST)

Contrast verification is covered by the Final verification checklist.

## High contrast / forced colors mode (MUST)

### Support OS-level accessibility features (MUST)

- Never override or disrupt OS accessibility settings.
- The UI MUST adapt to High Contrast / Forced Colors mode automatically.
- Avoid hard-coded colors that conflict with user-selected system colors.

### Adapt to OS-enforced color schemes (SHOULD)

Provide an alternative presentation when the OS enforces a high-contrast or reduced-color palette. Only apply overrides when the platform's default adaptation is not sufficient.

**Web implementation:**

Use `@media (forced-colors: active)` only when system defaults are not sufficient.

```css
@media (forced-colors: active) {
  /* Example: Replace box-shadow (suppressed in forced-colors) with a border */
  .button {
    border: 2px solid ButtonBorder;
  }
}

/* if using box-shadow for a focus style, also use a transparent outline
    so that the outline will render when the high contrast setting is enabled */
.button:focus {
  box-shadow: 0 0 4px 3px rgba(90, 50, 200, .7);
  outline: 2px solid transparent;
}
```

In Forced Colors mode, avoid relying on:

- Box shadows
- Decorative gradients

### Respect user color schemes in forced colors (MUST)

- Use system-provided color tokens when the OS enforces a color scheme. Do not use fixed color values in high-contrast overrides.
  - **Web:** Use system color keywords (e.g., `ButtonText`, `ButtonBorder`, `CanvasText`, `Canvas`). Do not use fixed hex/RGB colors inside `@media (forced-colors: active)`.

### Do not disable forced colors (MUST)

- Do not programmatically override or disable OS-level high contrast settings.
- If an override is required for a specific element, provide an accessible alternative that still works in high contrast mode.
  - **Web:** Do not use `forced-color-adjust: none` unless absolutely necessary and explicitly justified.

### Icons (MUST)

- Icons MUST adapt to the current text/foreground color. Do not embed fixed colors in icon assets.
  - **Web:** Use `currentColor` for SVG `fill`/`stroke`:

```css
svg {
  fill: currentColor;
  stroke: currentColor;
}
```

## Reflow (WCAG 2.2 SC 1.4.10) (MUST)

### Goal (MUST)

Multi-line text must be able to fit within narrow viewports (e.g., 320 CSS pixels wide), so that users do not need to scroll in two dimensions to read sections of content.

### Core principles (MUST)

- Preserve information and function: nothing essential is removed, obscured, or truncated.
- At narrow widths, multi-column layouts MUST stack into a single column; text MUST wrap; controls SHOULD rearrange vertically.
- Users MUST NOT need to scroll left/right to read multi-line text.
- If content is collapsed in the narrow layout, the full content/function MUST be available within 1 click (e.g., overflow menu, dialog, tooltip).

### Engineering requirements (MUST)

- Use responsive/fluid layout techniques; enable text wrapping.
- Avoid fixed widths that force two-dimensional scrolling at narrow viewport sizes.
- Avoid absolute positioning and clipping when it causes content loss or obscures content at smaller sizes.
- Media and containers should not overflow the viewport at narrow widths.
- Ensure layout children can shrink and wrap.
- Handle long strings (URLs, tokens) without forcing overflow.
- Ensure all interactive elements remain visible, reachable, and operable at narrow viewport sizes.

**Web implementation:**

- Use `flex`/`grid` with fluid sizing.
- Set `max-width: 100%` on media (images, video, canvas, iframes).
- Use `min-width: 0` on flex/grid children to allow shrinking.
- Use `overflow-wrap: anywhere` (or equivalent) for long strings.

### Exceptions (SHOULD)

If a component truly requires a two-dimensional layout for meaning/usage (e.g., large data tables, maps, diagrams, charts, games, presentations), allow horizontal scrolling only at the component level.

- The view as a whole MUST still reflow (unless the view layout truly requires two-dimensional layout for usage).
- The component MUST remain fully usable (all content reachable; controls operable).

## Controls and labels

### Visible labels (MUST)

- Every interactive element has a visible label.
- The label cannot disappear while entering text or after the field has a value.

### Voice access (MUST)

- The accessible name of each interactive element MUST contain the visible label text.
  - **Web:** If using `aria-label`, include the visible label text.
- If multiple controls share the same visible label (e.g., many "Remove" buttons), the accessible name must keep the visible label text and add context (e.g., "Remove item: Socks").
  - **Web:** Use `aria-label` with the visible text plus additional context.

## Forms

### Labels and help text (MUST)

- Every form control must have a programmatic label that describes its purpose.
- If help text exists, it must be programmatically associated with the control.
  - **Web:** Prefer `<label for="...">`. Associate help text via `aria-describedby`.

### Required fields (MUST)

- Indicate required fields both visually (often `*`) and programmatically.
  - **Web:** Use `aria-required="true"`.

### Errors and validation (MUST)

- Provide error messages that explain how to fix the issue.
- Mark invalid fields programmatically; clear the invalid state when corrected.
- Associate error messages with the field programmatically.
  - **Web:** Use `aria-invalid="true"` for invalid fields; remove it when valid. Associate inline errors via `aria-describedby`.
- Submit buttons SHOULD NOT be disabled solely to prevent submission.
- On submit with invalid input, focus the first invalid control.

## Graphics and images

- Informative graphics MUST have meaningful text alternatives.
- Decorative graphics MUST be hidden from assistive technology.

**Web implementation:**

- `<img>`: use `alt` for informative images; `alt=""` for decorative images.
- `<svg>`: prefer `role="img"` with `aria-label`/`aria-labelledby` for informative SVGs.
- Other decorative graphics: `aria-hidden="true"`.

## Navigation and menus

- Group navigation items logically using semantic navigation patterns.
- For expandable navigation, provide a toggle control that indicates its expanded/collapsed state.
- `Escape` MAY close open sub-navigations.

**Web implementation:**

- Use `<nav>` with lists and links.
- Do not use `role="menu"` / `role="menubar"` for site navigation.
- Use `aria-expanded` on toggle buttons to indicate state.

## Tables and grids

### Tables for static data (MUST)

- Use table semantics for static tabular data.
- Ensure header cells are programmatically associated with data cells.
  - **Web:** Use `<table>` with `<th>` elements. Column headers go in the first row; row headers (when present) use `<th>` in each row.

### Grids for dynamic UIs (SHOULD)

- Use grid semantics only for truly interactive/dynamic tabular experiences.
- Cells must be structured in rows so header/cell relationships are determinable.
- Use arrow-key navigation within the grid.
  - **Web:** Use `role="grid"` with proper row and cell nesting.

## Final verification checklist (MUST)

Before finalizing output, explicitly verify:

- Structure and semantics: regions/landmarks present, headings correct, one top-level heading for the view.
- Keyboard and focus: operable controls, visible focus, predictable tab order, no traps. Web: skip link works.
- Controls and labels: visible labels present and included in accessible names.
- Forms: programmatic labels, required indicators, errors associated with fields programmatically, focus first invalid on submit.
- Contrast: meets 4.5:1 / 3:1 thresholds, focus/boundaries meet 3:1, color not the only cue.
- Forced colors: does not break OS High Contrast / Forced Colors; adapts to system color settings.
- Reflow: content adjusts to narrow viewports without two-dimensional scrolling for multi-line text; no content loss; controls remain operable.
- Graphics: informative alternatives present; decorative graphics hidden.
- Tables/grids: tables have header association; grids (when needed) are structured with rows and cells.

## Final note

Generate accessible UI, but accessibility issues may still exist; manual review and testing with platform-appropriate tools (for example, Accessibility Insights for web) is still recommended.
