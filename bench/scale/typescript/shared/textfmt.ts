// Text helpers for names and labels.
export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function truncate(text: string, limit: number): string {
  if (limit < 1) throw new Error("limit must be at least 1");
  const flat = text.split(/\s+/).filter(Boolean).join(" ");
  return flat.length <= limit ? flat : flat.slice(0, limit - 1).trimEnd() + "…";
}
