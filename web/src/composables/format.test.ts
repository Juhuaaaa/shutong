import { describe, expect, it } from "vitest";
import { dropAttention, dropSummary, humanSize, scanSummary } from "./format";

describe("dropSummary", () => {
  it("counts each file once", () => {
    expect(dropSummary({ published: 3, executed: 3, known: 0, planned: 0 })).toBe("整理了 3 个文件");
  });

  it("says when everything was handled before", () => {
    expect(dropSummary({ known: 24, executed: 0, planned: 0 })).toBe("这些文件之前已经处理过（24 个）");
  });

  it("lists only what happened", () => {
    expect(dropSummary({ published: 2, needs_review: 1, failed: 1, known: 3 })).toBe(
      "整理了 2 个文件，1 个待复核，1 个失败，3 个之前已经处理过",
    );
  });

  it("does not call files the AI could not answer for nothing", () => {
    expect(dropSummary({ parsed: 10, known: 0, executed: 0, planned: 0 })).toBe("10 个还没整理完，再拖入一次可以继续");
    expect(dropAttention({ parsed: 10 })).toBe(true);
  });

  it("mentions duplicate volumes", () => {
    expect(dropSummary({ published: 1, duplicate: 2 })).toBe("整理了 1 个文件，2 个是重复的卷");
    expect(dropAttention({ published: 1, duplicate: 2 })).toBe(false);
  });

  it("does not claim success for an empty result", () => {
    expect(dropSummary({})).toBe("没有新文件需要整理");
  });
});

describe("format", () => {
  it("summarizes a scan with its counts", () => {
    expect(scanSummary({ executed: 3, planned: 0, needs_review: 2, published: 40, known: 5 })).toBe(
      "扫描完成：入库 3、待复核 2、已在库中 40",
    );
    expect(scanSummary({ needs_review: 1 })).toBe("扫描完成：入库 0、待复核 1、已在库中 0");
  });

  it("formats sizes", () => {
    expect([humanSize(512), humanSize(1536), humanSize(5 * 1024 ** 3)]).toEqual(["512 B", "1.5 KB", "5.0 GB"]);
  });
});
