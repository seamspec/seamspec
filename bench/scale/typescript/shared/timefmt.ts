// Timestamps and durations as text.
export function toIso(seconds: number): string {
  return new Date(Math.floor(seconds) * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function fromIso(text: string): number {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(text)) throw new Error(`not a timestamp: ${text}`);
  return Math.floor(Date.parse(text) / 1000);
}

export function durationText(seconds: number): string {
  if (seconds < 0) throw new Error("a duration can't be below zero");
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours}h ${String(minutes % 60).padStart(2, "0")}m` : `${minutes}m`;
}
