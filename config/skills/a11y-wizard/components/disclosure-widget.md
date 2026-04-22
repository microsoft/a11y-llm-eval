# Disclosure widget

A trigger that shows or hides a panel of content (FAQ answer, settings section, "show more").

## Principles

- The trigger is a real activatable control (not a plain link or text).
- The trigger exposes expanded/collapsed state to AT.
- The panel is removed from the accessibility tree and from focus order while hidden.
- Space / Enter activate the trigger; Tab leaves the widget after the panel.
- `Escape` MAY collapse an open panel and return focus to the trigger.
- Focus does not move into the panel automatically when it opens (disclosures are non-modal).

## Web implementation

### General defaults

- Trigger: `<button type="button" aria-expanded="false" aria-controls="panelId">`.
- Panel: a sibling element (`<div>`, `<section>`, etc.) with `id="panelId"` and `hidden` when collapsed.
- Toggle `aria-expanded` on the button and `hidden` on the panel together.
- Do **not** use `<a href="#">` as the trigger.

### Minimal pattern

```html
<h3>
  <button type="button" aria-expanded="false" aria-controls="cat-panel">
    Why do cats purr?
  </button>
</h3>
<div id="cat-panel" hidden>
  <p>Cats purr for many reasons — contentment, self-soothing, and healing.</p>
</div>

<script>
  document.querySelectorAll('[aria-controls]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const panel = document.getElementById(btn.getAttribute('aria-controls'));
      const open = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!open));
      panel.hidden = open;
    });
  });
</script>
```

### Review checklist

- Trigger is a `<button>` (not an `<a>` or a `<div>`).
- `aria-expanded` is present on the trigger and flips between `"true"` / `"false"` as the panel opens and closes.
- Panel has an `id` referenced by the trigger's `aria-controls`.
- When collapsed, the panel is `hidden` (or `display: none`) — not just visually hidden with CSS that leaves it focusable.
- Focus stays on the trigger when opening; users Tab into the panel themselves.
- If a group of disclosures, each has its own independent state — they don't behave like an accordion unless specified.
- Focus indicator is clearly visible on the trigger.

### Pitfalls

- `<a href="#">` as the trigger: appears navigable, breaks expected keyboard semantics, scrolls to top on activation.
- CSS-only show/hide (`opacity: 0`, `height: 0`) that keeps the panel in the focus order while it's visually hidden.
- Missing `aria-expanded`, so AT can't tell the state.
- Using `role="button"` on a `<div>` without implementing Enter/Space activation and focusability — use a native `<button>` instead.
- Trapping focus inside the panel — disclosures are non-modal.
