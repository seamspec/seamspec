// Settings read from environment variables.
export const PREFIX = "APP_";
export const DEFAULTS: Readonly<Record<string, number | boolean | string>> = Object.freeze({
  batch_size: 50,
  max_items: 500,
  verbose: false,
  region: "eu",
});

function convert(key: string, raw: string): number | boolean | string {
  const fallback = DEFAULTS[key];
  if (typeof fallback === "boolean") {
    if (raw !== "true" && raw !== "false") throw new Error(`${key}: expected true or false, got ${raw}`);
    return raw === "true";
  }
  if (typeof fallback === "number") {
    const value = Number(raw);
    if (!Number.isInteger(value) || value <= 0) throw new Error(`${key}: must be positive, got ${raw}`);
    return value;
  }
  if (!raw) throw new Error(`${key}: empty`);
  return raw;
}

export function load(env: Record<string, string>): Record<string, number | boolean | string> {
  const settings: Record<string, number | boolean | string> = { ...DEFAULTS };
  for (const [name, raw] of Object.entries(env)) {
    if (!name.startsWith(PREFIX)) continue;
    const key = name.slice(PREFIX.length).toLowerCase();
    if (!(key in DEFAULTS)) throw new Error(`unknown setting ${name}`);
    settings[key] = convert(key, raw.trim());
  }
  return settings;
}
