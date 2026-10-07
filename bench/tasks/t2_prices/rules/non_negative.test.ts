// Rule: discounts never make an order total negative.
import { expect, it } from "vitest";
import { totalCents } from "{{SRC}}/prices";

it("a discount larger than the order gives 0, not a negative total", () => {
  const items = [{ name: "a", unitCents: 300, qty: 1 }];
  expect(totalCents(items, 0, { kind: "amount", cents: 500 })).toBe(0);
  expect(totalCents(items, 0.1, { kind: "percent", percent: 100 })).toBe(0);
});
