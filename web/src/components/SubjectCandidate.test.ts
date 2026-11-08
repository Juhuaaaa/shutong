import { describe, expect, it } from "vitest";
import { mountWith } from "@/test-mount";
import SubjectCandidate from "./SubjectCandidate.vue";

const subject = {
  subject_id: "372334", source: "bangumi", web_url: "https://bgm.tv/subject/372334", aliases: [], name: "冴えない僕が君の部屋でしている事をクラスメイトは誰も知らない", name_cn: "不起眼的我在你房间做的事班上无人知晓",
  image: null, summary: "", release_date: "2022-01-01", writers: ["ヤマモトタケシ"], publisher: "KADOKAWA", genres: [],
  completed: false, total_volumes: null, platform: "漫画",
};

describe("SubjectCandidate", () => {
  it("opens the Bangumi page in a new tab without picking the candidate", async () => {
    const wrapper = mountWith(SubjectCandidate, { subject, selected: false });
    const link = wrapper.find("[data-test=candidate-open]");
    expect(link.attributes("href")).toBe("https://bgm.tv/subject/372334");
    expect(link.attributes("target")).toBe("_blank");
    expect(link.attributes("rel")).toContain("noopener");
    await link.trigger("click");
    await link.trigger("keydown", { key: "Enter" });
    expect(wrapper.emitted("pick")).toBeUndefined();
    await wrapper.find("[data-test=candidate]").trigger("click");
    expect(wrapper.emitted("pick")).toHaveLength(1);
  });

  it("names its source and links to that site", () => {
    const wrapper = mountWith(SubjectCandidate, {
      subject: { ...subject, subject_id: "30002", source: "anilist", web_url: "https://anilist.co/manga/30002",
        name_cn: "", name: "ベルセルク", aliases: ["Berserk"] },
      selected: false,
    });
    expect(wrapper.find("[data-test=candidate-source]").text()).toBe("AniList");
    expect(wrapper.find("[data-test=candidate-open]").attributes("href")).toBe("https://anilist.co/manga/30002");
    expect(wrapper.find(".name").text()).toBe("Berserk");
  });
});
