// Order totals for the shop. All money is in integer cents.

export type Item = { name: string; unitCents: number; qty: number };
export type Discount = { kind: "percent"; percent: number } | { kind: "amount"; cents: number };

/** Round a value in (fractional) cents to whole cents. Ties go to the even cent (banker's rounding). */
export function roundHalfEven(cents: number): number {
  const floor = Math.floor(cents);
  const diff = cents - floor;
  const eps = 1e-9;
  if (diff > 0.5 + eps) return floor + 1;
  if (diff < 0.5 - eps) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
}

export function subtotalCents(items: Item[]): number {
  return items.reduce((sum, item) => sum + item.unitCents * item.qty, 0);
}

/** Total in cents after an optional discount, then tax (a fraction such as 0.0825). */
export function totalCents(items: Item[], taxRate = 0, discount?: Discount): number {
  let cents = subtotalCents(items);
  if (discount?.kind === "percent") cents = cents * (1 - discount.percent / 100);
  if (discount?.kind === "amount") cents = cents - discount.cents;
  cents = Math.max(0, cents);
  return roundHalfEven(cents * (1 + taxRate));
}

export function formatCents(cents: number): string {
  const whole = Math.floor(cents / 100);
  const rest = String(cents % 100).padStart(2, "0");
  return `$${whole}.${rest}`;
}
