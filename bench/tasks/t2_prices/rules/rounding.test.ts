// Rule: order totals are rounded half-even ("banker's rounding") to whole cents.
import { expect, it } from "vitest";
import { totalCents } from "{{SRC}}/prices";

it("rounds ties to the even cent", () => {
  expect(totalCents([{ name: "a", unitCents: 1, qty: 1 }], 1.5)).toBe(2); // 2.5 -> 2
  expect(totalCents([{ name: "a", unitCents: 7, qty: 1 }], 0.5)).toBe(10); // 10.5 -> 10
});
