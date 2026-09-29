// 页面流程采用固定检索结果，真实向量计算及企业隔离由 PostgreSQL 测试覆盖。
import { expect, test } from "@playwright/test";

test("企业知识库保存草稿、发布、检索来源和停用", async ({ page }) => {
  const id = "11111111-1111-4111-8111-111111111111";
  let created = false;
  let published = false;
  let revision = 0;
  let drafts: { heading_path: string; content: string }[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = [];
    if (path === "/api/v1/access/staff") body = { id, audience: "staff", display_name: "客服", company_id: id, company_name: "测试企业" };
    else if (path === "/api/v1/staff/handoffs") body = { total: 0, items: [] };
    else if (path === "/api/v1/staff/knowledge") {
      if (route.request().method() === "POST") { created = true; body = {}; }
      else body = created ? [{ id, title: "售后政策", published, chunk_count: published ? 1 : 0, created_at: "2026-09-25T00:00:00Z" }] : [];
    } else if (path === `/api/v1/staff/knowledge/${id}`) {
      // 详情模拟真实入库片段，不把检索命中结果当作全部分块。
      body = { id, title: "售后政策", published, chunk_count: published ? 1 : 0,
        created_at: "2026-09-25T00:00:00Z", content: "签收七天内未使用可退货。",
        draft_chunks: drafts, draft_revision: revision, published_revision: published ? revision : 0, draft_warnings: [],
        chunks: published ? [{ id, position: 1, content: "签收七天内未使用可退货。", heading_path: "售后政策 / 退货", version: revision }] : [] };
    } else if (path.endsWith("/preview")) {
      revision++; drafts = [{ heading_path: "售后政策 / 退货", content: "签收七天内未使用可退货。" }]; body = {};
    } else if (path.endsWith("/draft")) {
      revision++; drafts = route.request().postDataJSON().chunks; body = {};
    } else if (path.endsWith("/publish")) { published = true; body = {}; }
    else if (path.endsWith("/disable")) { published = false; body = {}; }
    else if (path.endsWith("/search")) body = [{ document_id: id, chunk_id: id, title: "售后政策", position: 1, content: "签收七天内未使用可退货。", score: 0.92 }];
    await route.fulfill({ json: body });
  });
  await page.goto("/staff/knowledge");
  await page.getByPlaceholder("文档标题，例如：售后服务政策").fill("售后政策");
  await page.getByPlaceholder("粘贴正文，最多 60000 字符").fill("签收七天内未使用可退货。");
  await page.getByRole("button", { name: "保存草稿", exact: true }).click();
  await expect(page.getByText("草稿 · 0 个切片")).toBeVisible();
  await page.getByRole("button", { name: "预览与发布", exact: true }).click();
  await page.getByRole("button", { name: "生成分块预览", exact: true }).click();
  await expect(page.getByText("待发布片段 1", { exact: false })).toBeVisible();
  // 拆分、合并只操作草稿，保存前不允许发布。
  await page.getByRole("spinbutton").fill("5");
  await page.getByRole("button", { name: "拆分", exact: true }).click();
  await expect(page.getByText("待发布片段 2", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "确认分块并发布", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "与下一同章节片段合并", exact: true }).first().click();
  await page.getByRole("button", { name: "保存分块调整", exact: true }).click();
  await page.getByRole("button", { name: "确认分块并发布", exact: true }).click();
  await expect(page.getByText("发布成功，客服已使用此版本。")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByText("已发布 · 1 个切片")).toBeVisible();
  await page.getByRole("button", { name: "查看原文", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator(".knowledge-source")).toHaveText("签收七天内未使用可退货。");
  await dialog.getByRole("tab", { name: "已入库分块（1）" }).click();
  await expect(dialog.locator(".knowledge-hit")).toContainText("片段 1");
  await expect(dialog.locator(".knowledge-hit")).toContainText("签收七天内未使用可退货。");
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await page.getByPlaceholder("例如：退货需要满足什么条件？").fill("退货条件");
  await page.getByRole("button", { name: "测试检索", exact: true }).click();
  await expect(page.locator(".knowledge-panel .knowledge-hit")).toContainText("售后政策 · 片段 1");
  await expect(page.locator(".knowledge-panel .knowledge-hit")).toContainText("签收七天内未使用可退货。");
  await page.getByRole("button", { name: "停用", exact: true }).click();
  await expect(page.getByRole("button", { name: "预览与发布", exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
