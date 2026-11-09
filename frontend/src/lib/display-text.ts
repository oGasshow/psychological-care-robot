/** Normalize assistant/product names at display time without rewriting records. */
export function assistantDisplayText(value: unknown): string {
  return String(value ?? '').replace(/心翼(?:\s*xinyi)?|\bxinyi\b/gi, '陪伴助手');
}
