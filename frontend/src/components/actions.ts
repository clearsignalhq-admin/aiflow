/** One thing the top bar can do. The same list feeds the menus and the command palette, so they can never disagree. */
export interface ActionItem {
  id: string;
  label: string;
  /** Menu this action lives under (also shown in the palette). */
  group: string;
  /** One line shown under the label in the palette and as a tooltip. */
  hint?: string;
  shortcut?: string;
  onSelect?: () => void;
  disabled?: boolean;
  /** Why it is unavailable, shown as the tooltip. */
  disabledReason?: string;
}

export const isEnabled = (a: ActionItem): boolean => !!a.onSelect && !a.disabled;

/** Case-insensitive match of every word typed against label, group and hint. */
export function filterActions(actions: ActionItem[], query: string): ActionItem[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return actions;
  return actions.filter((a) => {
    const haystack = `${a.label} ${a.group} ${a.hint ?? ''}`.toLowerCase();
    return words.every((w) => haystack.includes(w));
  });
}
