import { useRef } from "react";

// Keyboard-first form navigation helpers.
const FOCUSABLE = 'input:not([type=hidden]):not([disabled]):not([tabindex="-1"]), select:not([disabled]):not([tabindex="-1"]), textarea:not([disabled]):not([tabindex="-1"]), button:not([disabled]):not([tabindex="-1"])';

export function focusables(root) {
  return Array.from(root.querySelectorAll(FOCUSABLE)).filter((el) => el.offsetParent !== null || el === document.activeElement);
}

export function focusFirst(root) {
  if (!root) return;
  const invalid = root.querySelector('[aria-invalid="true"]');
  const el = invalid || focusables(root).find((x) => x.tagName !== "BUTTON");
  el?.focus();
  el?.select?.();
}

export function moveFocus(root, from, step) {
  const list = focusables(root);
  const i = list.indexOf(from);
  if (i < 0) return false;
  const next = list[i + step];
  if (!next) return false;
  next.focus();
  next.select?.();
  return true;
}

/**
 * onKeyDown handler for a form container:
 *  Enter -> next field, Shift+Enter -> previous field, Ctrl/Cmd+S -> onSave, Esc -> onCancel.
 *  Enter on the last field -> onLastEnter (e.g. save row / add new row) or onSave.
 * A field can opt out with data-enter="native" (e.g. textarea, open combobox).
 */
export function formKeys({ onSave, onCancel, onLastEnter } = {}) {
  // Defer actions one tick so the focused field's own commit (Enter / blur) reaches state first.
  const later = (fn) => fn && setTimeout(fn, 0);
  return (e) => {
    const t = e.target;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      const el = document.activeElement;
      el?.blur?.(); // commit the field being typed in
      later(() => { onSave?.(); el?.focus?.(); });
      return;
    }
    if (e.key === "Escape" && onCancel && !e.defaultPrevented) {
      e.preventDefault();
      onCancel();
      return;
    }
    if (e.key !== "Enter") return;
    if (e.defaultPrevented) return; // the field rejected its value (stays focused) or handled Enter itself
    if (t.tagName === "TEXTAREA" && !e.ctrlKey) return;
    if (t.dataset.enter === "native" || t.tagName === "BUTTON") return;
    e.preventDefault();
    const root = e.currentTarget;
    const moved = moveFocus(root, t, e.shiftKey ? -1 : 1);
    if (!e.shiftKey) {
      const list = focusables(root).filter((x) => x.tagName !== "BUTTON");
      if (list[list.length - 1] === t || !moved) later(onLastEnter || onSave);
    }
  };
}

/**
 * Hook form of formKeys. Handlers are read through a ref at call time, so a deferred
 * save always sees the latest state (not the closure from the render that bound the key handler).
 */
export function useFormKeys(opts) {
  const ref = useRef(opts);
  ref.current = opts;
  return formKeys({
    onSave: () => ref.current.onSave?.(),
    onCancel: opts.onCancel ? () => ref.current.onCancel?.() : undefined,
    onLastEnter: opts.onLastEnter ? () => ref.current.onLastEnter?.() : undefined,
  });
}
