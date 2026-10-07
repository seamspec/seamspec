// Rule: order totals are rounded half-even ("banker's rounding") to whole cents.
import { expect, it } from "vitest";
import { totalCents } from "{{SRC}}/prices";

const one = (unitCents: number, qty = 1) => [{ name: "x", unitCents, qty }];

it("ties go to the even cent, both down and up", () => {
  expect(totalCents(one(3), 0.5)).toBe(4); // 4.5 -> 4 (half-up would give 5)
  expect(totalCents(one(1), 1.5)).toBe(2); // 2.5 -> 2
  expect(totalCents(one(13), 0.5)).toBe(20); // 19.5 -> 20
  expect(totalCents(one(1, 5), 0.5)).toBe(8); // 7.5 -> 8
});

it("non-ties round to the nearest cent", () => {
  expect(totalCents(one(999), 0.0825)).toBe(1081); // 1081.4175 -> 1081
  expect(totalCents(one(1001), 0.0825)).toBe(1084); // 1083.5825 -> 1084
});
