// 浏览器只模拟接口；真实权限和模型暂停另由后端数据库集成测试覆盖。
import { expect, test } from "@playwright/test";

test("一级页面直接发现待接管会话，一键接管回复并恢复智能客服", async ({ page }) => {
  const id = "11111111-1111-4111-8111-111111111111";
  const customer = "22222222-2222-4222-8222-222222222222";
  const company = "33333333-3333-4333-8333-333333333333";
  let status = "active";
  let content = "";
  // 故意挂起发送后的队列刷新，确保写请求成功即可结束按钮加载。
  let releaseRefresh!: () => void;
  const refreshGate = new Promise<void>((resolve) => { releaseRefresh = resolve; });
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = [];
    if (path === "/api/v1/access/staff") body = { id, audience: "staff", display_name: "客服", company_id: company, company_name: "企业" };
    else if (path === "/api/v1/staff/handoffs") {
      if (content) await refreshGate;
      const mine = new URL(route.request().url()).searchParams.get("scope") === "mine";
      const visible = mine ? status === "handed_off" : status === "active" && !content;
      body = { total: visible ? 1 : 0, items: visible ? [{ conversation_id: id, customer_name: "客户小王", requested_at: "2026-09-25T10:00:00Z", reason: "客户主动申请人工客服", status }] : [] };
    }
    else if (path === "/api/v1/staff/customers") body = [{ id: customer, display_name: "客户", conversation_count: 1, updated_at: "2026-09-21T00:00:00Z" }];
    else if (path === "/api/v1/staff/conversations") body = [{ id, customer_id: customer, customer_name: "客户", updated_at: "2026-09-21T00:00:00Z" }];
    else if (path.endsWith("/handoff")) {
      if (route.request().method() === "POST") status = route.request().postDataJSON().action === "takeover" ? "handed_off" : "active";
      body = { status, handoff_staff_id: status === "handed_off" ? id : null };
    } else if (path.endsWith("/reply")) {
      expect(status).toBe("handed_off");
      const data = route.request().postDataJSON();
      expect(data.client_request_id).toBeTruthy();
      content = data.content;
      body = {};
    } else if (path.endsWith("/messages")) body = [
      { id: customer, role: "customer", content: "较早的客户消息", created_at: "2026-09-20T00:00:00Z", tool_call: null },
      ...(content ? [{ id, role: "staff", content, created_at: "2026-09-21T00:00:00Z", tool_call: null }] : []),
    ];
    await route.fulfill({ json: body });
  });
  await page.goto("/staff/customers");
  const inbox = page.getByRole("region", { name: "人工接管待办" });
  await expect(inbox.getByText("客户小王", { exact: true })).toBeVisible();
  await expect(inbox.getByText("等待人工接管", { exact: true })).toBeVisible();
  await page.screenshot({ path: "/tmp/supportdesk-handoff-inbox.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(inbox.getByRole("button", { name: "立即接管并回复" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "/tmp/supportdesk-handoff-inbox-mobile.png", fullPage: true });
  // 不点客户名称，不打开历史会话，直接从一级待办进入回复框。
  await inbox.getByRole("button", { name: "立即接管并回复" }).click();
  await expect(page.getByText("人工接管中 · AI 暂停回复")).toBeVisible();
  await page.getByPlaceholder("输入人工回复").fill("您好，我来协助处理。");
  await page.getByRole("button", { name: "发送人工回复" }).click();
  try {
    await expect(page.getByText("回复已发送。输入新内容即可继续回复。", { exact: true })).toBeVisible();
    const send = page.getByRole("button", { name: "发送人工回复", exact: true });
    await expect(send).not.toHaveClass(/is-loading/);
    await expect(send).toBeDisabled(); // 空输入框的禁用不等于仍在发送。
    await expect(page.getByPlaceholder("输入人工回复")).toBeEnabled();
    await page.getByPlaceholder("输入人工回复").fill("下一条回复");
    await expect(send).toBeEnabled();
    await page.getByPlaceholder("输入人工回复").clear();
  } finally {
    releaseRefresh();
  }
  await expect(page.getByText("您好，我来协助处理。", { exact: true })).toBeVisible();
  await expect(page.locator(".el-drawer .customer-message p")).toHaveText(["您好，我来协助处理。", "较早的客户消息"]);
  await page.getByRole("button", { name: "恢复智能客服" }).click();
  await expect(page.getByText("智能客服服务中", { exact: true })).toBeVisible();
  await expect(page.getByPlaceholder("输入人工回复")).toHaveCount(0);
  await page.locator(".el-drawer__close-btn").click();
  await expect(inbox.getByText(/暂无待接管会话/)).toBeVisible();
  // 普通会话查看区也采用相同顺序，不能只修接管抽屉。
  await page.getByRole("button", { name: "查看会话", exact: true }).click();
  await page.getByRole("button", { name: /查看 .* 的会话/ }).click();
  await expect(page.locator(".portal-panel .customer-message p")).toHaveText(["您好，我来协助处理。", "较早的客户消息"]);
});

test("客户人工模式发送不伪造 AI 回复，并轮询收到客服回复", async ({ page }) => {
  const id = "11111111-1111-4111-8111-111111111111";
  const company = "33333333-3333-4333-8333-333333333333";
  let sent = false;
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = [];
    if (path === "/api/v1/access/customer") body = { id, audience: "customer", display_name: "客户", company_id: null, company_name: null };
    else if (path === `/api/v1/customer/companies/${company}`) body = { id: company, name: "企业", code: "demo" };
    else if (path === "/api/v1/customer/conversations") body = [{ id, customer_id: id, company_id: company, updated_at: "2026-09-21T00:00:00Z" }];
    else if (path.endsWith("/handoff")) body = { status: "handed_off", handoff_staff_id: id };
    else if (path === "/api/v1/agent/chat") {
      sent = true;
      body = { conversation_id: id, customer_message_id: id, agent_message_id: null, agent_run_id: null, delivery_mode: "human", reply: "", intent: "general", priority: "medium", requires_human: true, reason: "消息已提交人工客服", created_ticket_id: null, created_ticket_code: null };
    } else if (path.endsWith("/messages")) body = sent ? [{ id, role: "staff", content: "客服小李：您好，已收到。", created_at: "2026-09-21T00:00:00Z", tool_call: null }] : [];
    await route.fulfill({ json: body });
  });
  await page.goto(`/customer/companies/${company}/chat`);
  await page.getByText("查看与该企业的历史会话", { exact: true }).click();
  await page.getByRole("button", { name: /11111111/ }).click();
  await expect(page.getByText("人工客服已接管，您的消息将直接提交客服，智能客服暂停回复。")).toBeVisible();
  await page.getByPlaceholder("请描述您的问题、影响和期望的处理结果").fill("请帮忙处理");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByText("客服小李：您好，已收到。", { exact: true })).toBeVisible();
  await expect(page.locator(".customer-message.staff small")).toContainText("人工客服");
});
