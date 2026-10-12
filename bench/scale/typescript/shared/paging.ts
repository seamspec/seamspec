// Pages of a list, for the admin screens.
export const LARGEST_PAGE = 100;

export interface Page<T> {
  items: T[];
  page: number;
  size: number;
  total: number;
}

export function page<T>(items: T[], number = 1, size = 20): Page<T> {
  if (number < 1 || size < 1) throw new Error("page number and size start at 1");
  const capped = Math.min(size, LARGEST_PAGE);
  const start = (number - 1) * capped;
  return { items: items.slice(start, start + capped), page: number, size: capped, total: items.length };
}
