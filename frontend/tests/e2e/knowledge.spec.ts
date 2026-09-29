// 页面流程采用固定检索结果，真实向量计算及企业隔离由 PostgreSQL 测试覆盖。
import { expect, test } from "@playwright/test";

test("历史工单经验需要审核才能发布", async ({ page }) => {
  const id = "11111111-1111-4111-8111-111111111111";
  let created = false;
  let revision = 0;
  let published = false;
  const summary = () => ({ id, title: "断连处理经验", source_kind: "ticket_case", published, chunk_count: published ? 1 : 0, created_at: "2026-09-29T00:00:00Z" });
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = [];
    if (path === "/api/v1/access/staff") body = { id, audience: "staff", display_name: "客服", company_id: id, company_name: "测试企业" };
    else if (path === "/api/v1/staff/handoffs") body = { total: 0, items: [] };
    else if (path.endsWith("/ticket-experiences/candidates")) body = [
      { code: "TK-test", title: "断连处理经验", status: "closed" },
      { code: "TK-other", title: "机器故障，客户要求退货", status: "closed" },
    ];
    else if (path.endsWith("/ticket-experiences/source")) body = { code: "TK-test", title: "断连处理经验", status: "closed", description: "间歇断连", desired_resolution: "希望退款", impact_note: "" };
    else if (path.endsWith("/ticket-experiences")) { created = true; body = summary(); }
    else if (path === "/api/v1/staff/knowledge") body = created ? [summary()] : [];
    else if (path.endsWith("/preview")) { revision = 1; body = summary(); }
    else if (path.endsWith("/publish")) {
      expect(route.request().postDataJSON().confirm_case_review).toBe(true);
      published = true; body = summary();
    } else if (path.endsWith(id)) body = { ...summary(), content: "通用解决经验", chunks: [], draft_revision: revision,
      published_revision: published ? revision : 0, draft_warnings: [],
      draft_chunks: revision ? [{ heading_path: "断连处理经验", content: "重新插入接收器后恢复" }] : [] };
    await route.fulfill({ json: body });
  });
  // 带编号入口首次读取后离开再返回，查询缓存仍在，但表单组件会重新创建。
  // 相同响应不会触发数据变化，必须覆盖这种容易漏掉的再次进入场景。
  await page.goto("/staff/knowledge?experience=TK-test");
  await expect(page.getByPlaceholder("例如：无线键盘间歇断连的处理经验")).toHaveValue("断连处理经验");
  await page.keyboard.press("Escape");
  await page.getByRole("link", { name: "工单处理", exact: true }).click();
  await expect(page).toHaveURL(/\/staff\/tickets$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/staff\/knowledge\?experience=TK-test$/);
  await expect(page.getByPlaceholder("例如：无线键盘间歇断连的处理经验")).toHaveValue("断连处理经验");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "从工单整理经验", exact: true }).click();
  // 打开入口即能看到数据库候选，无需再展开一个隐藏列表。
  await expect(page.getByText("TK-test · 已关闭", { exact: true })).toBeVisible();
  await expect(page.getByText("机器故障，客户要求退货", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "读取工单 TK-other", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "读取工单 TK-test", exact: true }).click();
  await expect(page.getByPlaceholder("例如：无线键盘间歇断连的处理经验")).toHaveValue("断连处理经验");
  await expect(page.getByPlaceholder("例如：无线键盘间歇断连，不填写客户姓名或账号")).toHaveValue("间歇断连");
  await expect(page.getByPlaceholder("填写该工单实际采用并验证的处理步骤")).toHaveValue("");
  await page.getByPlaceholder("填写已核实原因；不能确认时请写“未确认”，不要猜测").fill("接收器松动");
  await page.getByPlaceholder("填写该工单实际采用并验证的处理步骤").fill("重新插入接收器");
  await page.getByPlaceholder("例如：仅适用于接收器接触不良，不适用于进水或硬件损坏").fill("仅接触不良");
  await page.getByRole("button", { name: "保存经验草稿并审核" }).click();
  await page.getByRole("button", { name: "生成分块预览", exact: true }).click();
  const publish = page.getByRole("button", { name: "确认分块并发布", exact: true });
  await expect(publish).toBeDisabled();
  await expect(page.getByText("待发布片段 1", { exact: false })).toBeVisible();
  await page.getByText("我已审核当前分块：完成脱敏、内容属实，允许向本企业客户公开", { exact: true }).click();
  await publish.click();
  await expect(page.getByText("发布成功，客服已使用此版本。")).toBeVisible();
});

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
