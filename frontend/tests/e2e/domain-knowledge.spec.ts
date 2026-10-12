// 用同一知识包验证页面，所有 HTTP 都被替换，不连接业务数据或收费模型。
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const catalog: unknown = JSON.parse(readFileSync(new URL("../../../backend/app/knowledge/after_sales.v1.json", import.meta.url), "utf8"));

test("领域知识只读浏览、完整路径与故障状态", async ({ page }, testInfo) => {
  let fail = false;
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/knowledge-graph/catalog")) {
      expect(route.request().method()).toBe("GET");
      await route.fulfill(fail ? { status: 503, json: { detail: "领域图谱暂不可用" } } : { json: catalog });
      return;
    }
    await route.fulfill({ json: path.endsWith("/access/staff") ? {
      id: "11111111-1111-4111-8111-111111111111", audience: "staff", display_name: "客服", company_id: "11111111-1111-4111-8111-111111111111", company_name: "测试企业",
    } : { total: 0, items: [] } });
  });
  await page.goto("/staff/knowledge-graph");
  await expect(page.getByRole("heading", { name: "售后领域知识图谱" })).toBeVisible();
  await expect(page.getByText("2 条完整路径", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "AI 抽取关系" })).toHaveCount(0);
  await expect(page.getByText("必须满足 · 未知不等于满足", { exact: true })).toHaveCount(2);
  await page.getByLabel("产品类别", { exact: true }).selectOption("wireless-keyboard");
  await page.getByLabel("问题现象", { exact: true }).selectOption("disconnecting");
  await expect(page.getByText("匹配 2 条排查路径", { exact: true })).toBeVisible();
  const receiver = page.locator(".diagnostic-path").filter({ hasText: "接收器连接不稳" });
  await expect(receiver.getByText("重新插接后恢复连接", { exact: true })).toBeVisible();
  await expect(receiver.getByText("已确认电量不足", { exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("domain-knowledge.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  fail = true;
  await page.getByRole("button", { name: "刷新知识状态" }).click();
  await expect(page.getByText("领域图谱暂不可用", { exact: true })).toBeVisible();
  await expect(page.locator(".diagnostic-path")).toHaveCount(0);
});
