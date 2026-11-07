import { describe, expect, it } from "vitest";
import { mountWith } from "@/test-mount";
import BrandMark from "./BrandMark.vue";

describe("BrandMark", () => {
  it("draws the book-and-tick logo at the requested size", () => {
    const mark = mountWith(BrandMark, { size: 48 }).get("[data-test=brand-mark]");
    expect(mark.attributes("style")).toContain("width: 48px");
    expect(mark.findAll("path")).toHaveLength(3);
    expect(mark.get("svg").attributes("width")).toBe(String(48 * 0.7));
  });
});
