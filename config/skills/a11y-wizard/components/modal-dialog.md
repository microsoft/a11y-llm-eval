# Modal dialog

A blocking overlay for focused tasks or destructive confirmations (e.g., "Delete this image?").

## Principles

- A modal dialog has an accessible name and role exposing it as a dialog.
- Opening the dialog moves focus into it (usually the first focusable control, or the primary action for confirmations).
- Background content is inert to AT, keyboard, and pointer while the dialog is open.
- Focus is trapped inside the dialog until it closes.
- Closing the dialog restores focus to the element that opened it.
- `Escape` closes the dialog (if closable); clicking outside MAY close it (depending on destructiveness).
- Dialog content is scrollable if it exceeds the viewport; the background does not scroll.

## Web implementation

### Preferred: native `<dialog>`

- Use `<dialog>` with `.showModal()`. The browser handles focus trap, background inertness, Escape, and the backdrop.
- Give the dialog an accessible name via `aria-labelledby` referencing the heading inside.

### Minimal pattern (native `<dialog>`)

```html
<button type="button" id="delete-btn">Delete image</button>

<dialog id="confirm-dialog" aria-labelledby="confirm-heading">
  <h2 id="confirm-heading">Delete this image?</h2>
  <p>This action can't be undone.</p>

  <button type="button" value="cancel" data-close>Cancel</button>
  <button type="button" value="delete" data-confirm>Delete</button>
</dialog>

<script>
  const dialog = document.getElementById('confirm-dialog');
  const trigger = document.getElementById('delete-btn');

  trigger.addEventListener('click', () => dialog.showModal());
  dialog.querySelector('[data-close]').addEventListener('click', () => dialog.close('cancel'));
  dialog.querySelector('[data-confirm]').addEventListener('click', () => dialog.close('delete'));
  dialog.addEventListener('close', () => trigger.focus());
</script>
```

### Fallback: ARIA dialog

When `<dialog>` isn't an option:

- Container: `role="dialog"` or `role="alertdialog"` (the latter for short destructive confirmations), `aria-modal="true"`, `aria-labelledby` referencing the title, optional `aria-describedby` for the body.
- Use `inert` on all siblings of the dialog while it's open to make the rest of the page non-interactive.
- Implement a focus trap: when focus reaches the last focusable element, Tab wraps to the first; Shift+Tab from the first wraps to the last.
- Handle `Escape` to close.
- Restore focus to the trigger on close.

```html
<div role="alertdialog" aria-modal="true"
     aria-labelledby="confirm-heading" aria-describedby="confirm-body">
  <h2 id="confirm-heading">Delete this image?</h2>
  <p id="confirm-body">This action can't be undone.</p>
  <button type="button">Cancel</button>
  <button type="button">Delete</button>
</div>
```

### Review checklist

- Dialog has a programmatic role (`<dialog>` or `role="dialog"` / `role="alertdialog"`) and an accessible name.
- Opening moves focus into the dialog.
- While open, background is inert (native `<dialog>.showModal()` or `inert` on siblings).
- Focus is trapped inside the dialog.
- `Escape` closes the dialog.
- Closing restores focus to the trigger.
- Dialog is reachable only when open; hidden from AT / focus order when closed.
- Content can scroll within the dialog if it overflows; the background doesn't scroll.
- Destructive actions use `role="alertdialog"` or a clearly-named dialog; the default/initial focus does not land on the destructive action.

### Pitfalls

- Opening a dialog without moving focus — keyboard users are stranded on the trigger.
- Not restoring focus on close — keyboard users lose their place.
- Forgetting `inert` on background content in the ARIA fallback — Tab escapes the dialog.
- Using `role="dialog"` without `aria-modal="true"` and then trapping focus anyway — mismatched semantics.
- Auto-focusing the destructive button on open — accidental confirmation via Enter/Space.
