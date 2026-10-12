// Log lines for the log collector.
export const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"];
const MASKED = ["password", "token", "secret"];

export function line(level: string, message: string, fields: Record<string, unknown> = {}): string {
  const upper = level.toUpperCase();
  if (!LEVELS.includes(upper)) throw new Error(`unknown level ${level}`);
  const record: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(fields)) {
    if (key === "level" || key === "message") continue;
    record[key] = MASKED.includes(key.toLowerCase()) ? "***" : value;
  }
  record.level = upper;
  record.message = String(message);
  const sorted = Object.fromEntries(Object.keys(record).sort().map((key) => [key, record[key]]));
  return JSON.stringify(sorted).replace(/[\u0080-￿]/g, (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
}
