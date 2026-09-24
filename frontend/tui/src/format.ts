/**
 * Small display helpers shared by the TUI footer and progress panel.
 *
 * They live outside `app.tsx` so the column/fit rules are unit-testable
 * without booting the OpenTUI renderer.
 */

/** Keep the tail of a long path so a footer line still fits 80 columns. */
export function compactPath(value: string, max = 30): string {
  if (!value || value.length <= max) return value
  return `…${value.slice(value.length - (max - 1))}`
}

/** GitHub URLs differ at both ends (`owner/repo` vs `pull/123`), so cut the middle. */
export function truncateMiddle(value: string, max = 70): string {
  if (value.length <= max) return value
  const head = Math.ceil((max - 1) / 2)
  const tail = Math.floor((max - 1) / 2)
  return `${value.slice(0, head)}…${value.slice(value.length - tail)}`
}

/**
 * Render the workspace root the launcher reported, folding the home prefix to
 * `~`. The footer used to hard-code `~\Desktop\ican`, which lied for every
 * other checkout (and for the packaged build).
 */
export function workspaceRootLabel(
  root: string = typeof process !== "undefined" ? process.env?.AI_PR_REVIEW_ROOT ?? process.cwd?.() ?? "" : "",
  home: string = typeof process !== "undefined" ? process.env?.USERPROFILE ?? process.env?.HOME ?? "" : "",
  max = 30,
): string {
  if (!root) return ""
  const display =
    home && root.toLowerCase().startsWith(home.toLowerCase()) ? `~${root.slice(home.length)}` : root
  return compactPath(display, max)
}
