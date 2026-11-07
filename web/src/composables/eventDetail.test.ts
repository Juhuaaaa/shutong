import { describe, expect, it } from "vitest";
import { eventDetail } from "./eventDetail";

describe("eventDetail", () => {
  it("writes a readable line without JSON", () => {
    const line = eventDetail({ note: "no volume number", series: "迷宫饭", target: null });
    expect(line).toBe("认不出卷号；系列：迷宫饭");
    expect(eventDetail({ method: "search", subject_id: 133315, title: "迷宫饭" })).toBe("方式：search；Bangumi：133315；名称：迷宫饭");
    expect(eventDetail({ sha256: "ab", volume: "chapter:15", candidates: [1, 2] })).toBe("卷号：Ch.15；候选：1、2");
  });

  it("keeps unknown notes and keys as they are", () => {
    expect(eventDetail({ note: "something new", extra: 3 })).toBe("something new；extra：3");
    expect(eventDetail({})).toBe("");
  });
});
