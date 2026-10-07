import { describe, expect, it } from "vitest";
import { formatCents, subtotalCents, totalCents } from "../src/prices";

describe("prices", () => {
  it("adds up items", () => {
    expect(subtotalCents([{ name: "a", unitCents: 250, qty: 2 }, { name: "b", unitCents: 99, qty: 1 }])).toBe(599);
  });
  it("applies tax", () => {
    expect(totalCents([{ name: "a", unitCents: 1000, qty: 1 }], 0.08)).toBe(1080);
  });
  it("formats cents", () => {
    expect(formatCents(1205)).toBe("$12.05");
  });
});
