/**
 * Vertical scroll delta for the finding detail panel.
 *
 * `Shift+↑/↓` is used instead of plain arrows because plain arrows already
 * move the finding selection.
 */
export function detailScrollDelta(
  name: string,
  shift: boolean,
  ctrl = false,
  meta = false,
): number | undefined {
  if (!shift && !ctrl && !meta) return undefined
  if (name === "up") return -1
  if (name === "down") return 1
  return undefined
}
