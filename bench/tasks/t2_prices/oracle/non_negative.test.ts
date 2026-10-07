// Rule: discounts never make an order total negative.
import { expect, it } from "vitest";
import { totalCents } from "{{SRC}}/prices";

const small = [{ name: "gum", unitCents: 99, qty: 1 }];

it("no discount shape can push a total below zero", () => {
  expect(totalCents(small, 0, { kind: "amount", cents: 500 })).toBeGreaterThanOrEqual(0);
  expect(totalCents(small, 0.2, { kind: "amount", cents: 10_000 })).toBeGreaterThanOrEqual(0);
  expect(totalCents(small, 0, { kind: "percent", percent: 100 })).toBe(0);
  expect(totalCents(small, 0.0825, { kind: "percent", percent: 150 })).toBeGreaterThanOrEqual(0);
});
