import type { JobBoard } from "../api/types";

// Display labels for board keys whose raw catalog key reads badly. Absent
// keys fall back to the key itself, so adding a board never requires an entry
// here.
export const BOARD_LABELS: Record<string, string> = { remoterocketship: "Remote Rocketship" };

export function boardLabel(board: JobBoard): string {
  return BOARD_LABELS[board.source.toLowerCase()] ?? (board.domain || board.source);
}
