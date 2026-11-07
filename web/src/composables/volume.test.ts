import { describe, expect, it } from "vitest";
import { editionOf, isVolumeText, subjectIdOf } from "./volume";

describe("isVolumeText", () => {
  it("accepts the forms the backend reads", () => {
    for (const text of ["13", "1.5", "01-05", "SP1", "sp 01", "Ch.15", "ch15", "第15话", "15話"]) expect(isVolumeText(text)).toBe(true);
    for (const text of ["第一卷", "05-01", "Vol", "第15卷"]) expect(isVolumeText(text)).toBe(false);
  });

  it("takes fewer forms for a novel", () => {
    expect(["2", "12.5", "SP1"].every((text) => isVolumeText(text, "novel"))).toBe(true);
    expect(["1-5", "Ch.15", "第15话"].some((text) => isVolumeText(text, "novel"))).toBe(false);
  });

  it("reads a subject id from a number or a link", () => {
    expect(subjectIdOf("439286")).toBe(439286);
    expect(subjectIdOf("https://bgm.tv/subject/439286")).toBe(439286);
    expect(subjectIdOf(" https://bangumi.tv/subject/12?x=1 ")).toBe(12);
    expect(subjectIdOf("魔法禁书目录")).toBeNull();
    expect(subjectIdOf("0")).toBeNull();
  });

  it("reads the edition from a folder name", () => {
    expect(editionOf("婚戒物语[东立电子版]")).toBe("东立电子版");
    expect(editionOf("迷宫饭")).toBeNull();
  });
});
