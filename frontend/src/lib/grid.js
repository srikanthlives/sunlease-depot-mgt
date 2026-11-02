// Spreadsheet-style arrow navigation: cells are <td data-row=".." data-col="..">.
export function gridArrows(e) {
  if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
  const t = e.target;
  if (t.getAttribute("role") === "combobox" || t.tagName === "SELECT" || t.getAttribute("aria-label") === "Day offset") return;
  const td = t.closest("[data-row]");
  if (!td) return;
  const row = Number(td.dataset.row) + (e.key === "ArrowDown" ? 1 : -1);
  const target = e.currentTarget.querySelector(`[data-row="${row}"][data-col="${td.dataset.col}"] input`);
  if (target) {
    e.preventDefault();
    target.focus();
    target.select?.();
  }
}

export function focusCell(root, row, col) {
  setTimeout(() => {
    const el = root?.querySelector(`[data-row="${row}"][data-col="${col}"] input, [data-row="${row}"][data-col="${col}"] select`);
    el?.focus();
    el?.select?.();
  }, 20);
}
