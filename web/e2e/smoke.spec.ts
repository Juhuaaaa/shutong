import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const data = resolve("test-results/e2e");

test("set up, scan into the library, review and see it in the history", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("首次使用")).toBeVisible();
  await page.fill("input[type=password]", "e2e password");
  await page.click("button[type=submit]");
  await expect(page.getByText("还没有库")).toBeVisible();

  // Recognition needs an AI: e2e/fake_ai.py answers on this port (see playwright.config.ts).
  await page.goto("/settings/ai");
  await page.locator("[data-test=ai-url] input").fill("http://127.0.0.1:8795/v1");
  await page.locator("[data-test=ai-key] input").fill("e2e-key");
  await page.locator("[data-test=ai-model] input").fill("fake");
  await page.locator("[data-test=save-ai]").click();
  await expect(page.getByText("已保存")).toBeVisible();

  await page.locator("[data-test=nav-libraries]").click();
  await page.locator("[data-test=create]").click();
  const card = page.locator("[data-test=library-card]").first();
  await card.locator("[data-test=name] input").fill("漫画");
  await card.locator("[data-test=source-dir] input").fill(`${data}/source`);
  await card.locator("[data-test=library-dir] input").fill(`${data}/library`);
  await card.locator("[data-test=save]").click();
  await expect(page.locator("[data-test=library-card]").filter({ hasText: "漫画" })).toBeVisible();

  await page.locator("[data-test=scan]").click();
  await expect(page.getByText("扫描完成：入库 74、待复核 1")).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/libraries.png" });
  await expect(page.locator("[data-test=nav-preview]")).toHaveCount(0);

  await page.locator("[data-test=nav-review]").click();
  await expect(page.locator("[data-test=detail]")).toContainText("[]");
  await page.locator("[data-test=title] input").fill("婚戒物语");
  await page.locator("[data-test=bgm] input").fill("98253");
  await page.screenshot({ path: "e2e/screenshots/review.png" });
  await page.locator("[data-test=confirm]").click();
  await expect(page.getByText(/已确认/)).toBeVisible();

  await page.locator("[data-test=nav-history]").click();
  await expect(page.locator("[data-test=history-group]")).toHaveCount(4);
  await expect(page.locator("[data-test=history-group]").filter({ hasText: "迷宫饭" })).toContainText("已整理 2");
  await expect(page.locator("[data-test=history-group]").filter({ hasText: "婚戒物语" })).toContainText("已整理 1");
  await expect(page.locator("[data-test=history-group]").filter({ hasText: "大王饶命" })).toContainText("已整理 2");
  // 70 volumes: a virtual list renders some rows, never all of them.
  const big = page.locator("[data-test=history-group]").filter({ hasText: "極道超女" });
  await big.locator("[role=button]").first().click();
  await expect(big.locator("[data-test=group-item]").first()).toBeVisible();
  expect(await big.locator("[data-test=group-item]").count()).toBeLessThan(70);
  await big.locator("[data-test=item-details]").first().click();
  await expect(page.locator("[data-test=timeline]")).toBeVisible();
  await expect(page).toHaveURL(/item=/);
  await page.screenshot({ path: "e2e/screenshots/history.png" });
  await page.keyboard.press("Escape");

  await page.locator("[data-test=nav-dashboard]").click();
  await expect(page.locator("[data-test=stat-volumes]")).toContainText("75");
  await expect(page.locator("[data-test=recent]")).toHaveCount(4);
  await page.screenshot({ path: "e2e/screenshots/dashboard.png" });
});
