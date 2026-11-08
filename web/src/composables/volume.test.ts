import { describe, expect, it } from "vitest";
import { editionOf, isVolumeText, subjectRefOf } from "./volume";

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
    expect(subjectRefOf("439286", "bangumi")).toEqual({ source: "bangumi", id: "439286" });
    expect(subjectRefOf("30002", "anilist")).toEqual({ source: "anilist", id: "30002" });
    expect(subjectRefOf("https://bgm.tv/subject/439286", "anilist")).toEqual({ source: "bangumi", id: "439286" });
    expect(subjectRefOf(" https://bangumi.tv/subject/12?x=1 ", "bangumi")).toEqual({ source: "bangumi", id: "12" });
    expect(subjectRefOf("https://anilist.co/manga/30002/Berserk/", "bangumi")).toEqual({ source: "anilist", id: "30002" });
    expect(subjectRefOf("魔法禁书目录", "bangumi")).toBeNull();
    expect(subjectRefOf("0", "bangumi")).toBeNull();
    expect(subjectRefOf("https://example.com/subject/3", "bangumi")).toBeNull();
  });

  it("reads the edition from a folder name", () => {
    expect(editionOf("婚戒物语[东立电子版]")).toBe("东立电子版");
    expect(editionOf("迷宫饭")).toBeNull();
  });
});
