// 页面交互使用模拟接口；真实数据库认证与跨租户访问另由后端集成测试验证。
import { test, expect } from "@playwright/test";
const customerId = "11111111-1111-4111-8111-111111111111";
const companyA = { id: "22222222-2222-4222-8222-222222222222", name: "甲企业", code: "alpha" };
const companyB = { id: "33333333-3333-4333-8333-333333333333", name: "乙企业", code: "beta" };
const conversationId = "44444444-4444-4444-8444-444444444444";
const messageId = "55555555-5555-4555-8555-555555555555";

test("客户注册登录后选择企业，聊天请求绑定企业，员工认证独立", async ({ page }) => {
  let customerLoggedIn = false;
  let staffLoggedIn = false;
  const submitted: string[] = [];
  const customer = { id: customerId, audience: "customer", display_name: "客户小陈", company_id: null, company_name: null };
  const staff = { id: messageId, audience: "staff", display_name: "客服小李", company_id: companyA.id, company_name: companyA.name };
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: object = { ready: true };
    let status = 200;
    if (path === "/api/v1/access/customer") { status = customerLoggedIn ? 200 : 401; body = customer; }
    else if (path === "/api/v1/access/staff") { status = staffLoggedIn ? 200 : 401; body = staff; }
    else if (path === "/api/v1/access/customer/login") { customerLoggedIn = true; body = customer; }
    else if (path === "/api/v1/access/staff/login") { staffLoggedIn = true; body = staff; }
    else if (path === "/api/v1/access/staff/logout") staffLoggedIn = false;
    else if (path === "/api/v1/access/customer/logout") customerLoggedIn = false;
    else if (path === "/api/v1/customer/companies") body = [companyA, companyB];
    else if (path === "/api/v1/customer/companies/" + companyA.id) body = companyA;
    else if (path === "/api/v1/customer/companies/" + companyB.id) body = companyB;
    else if (path === "/api/v1/customer/conversations" || path === "/api/v1/staff/conversations" || path === "/api/v1/staff/customers") body = [];
    else if (path === "/api/v1/agent/chat") {
      const input = route.request().postDataJSON() as { company_id: string };
      submitted.push(input.company_id);
      body = { conversation_id: conversationId, customer_message_id: customerId, agent_message_id: messageId, agent_run_id: messageId, reply: "已收到您的咨询", intent: "general", priority: "low", requires_human: false, reason: "普通问题", created_ticket_id: null, created_ticket_code: null };
    } else if (path.endsWith("/messages")) body = [{ id: messageId, role: "agent", content: "已收到您的咨询", created_at: "2026-09-12T00:00:00Z", tool_call: null }];
    else if (path === "/api/v1/customer/tickets" || path === "/api/v1/tickets") body = { items: [], total: 0, offset: 0, limit: 20 };
    else if (path === "/api/v1/tickets/statistics") body = { total: 0, open: 0, in_progress: 0, waiting_customer: 0, resolved: 0, closed: 0 };
    await route.fulfill({ status, json: body });
  });
  await page.goto("/");
  await expect(page).toHaveURL(/\/customer\/login$/);
  await page.getByRole("button", { name: "注册客户账号", exact: true }).click();
  await page.getByLabel("您的称呼", { exact: true }).fill("客户小陈");
  await page.getByLabel("账号", { exact: true }).fill("customer");
  await page.locator('input[type="password"]').fill("12345678");
  await page.getByRole("button", { name: "注册", exact: true }).click();
  await expect(page.getByText("注册成功，请使用刚创建的账号和密码登录。")).toBeVisible();
  await page.locator('input[type="password"]').fill("12345678");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "选择您要咨询的企业" })).toBeVisible();
  await page.getByRole("link", { name: "咨询该企业 →" }).first().click();
  await expect(page).toHaveURL(new RegExp(companyA.id + "/chat"));
  await expect(page.getByRole("heading", { name: "甲企业", exact: true })).toBeVisible();
  await page.getByPlaceholder("请描述您的问题、影响和期望的处理结果").fill("你好甲企业");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByText("已收到您的咨询", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "选择企业", exact: true }).click();
  await page.getByRole("link", { name: "咨询该企业 →" }).nth(1).click();
  await expect(page).toHaveURL(new RegExp(companyB.id + "/chat"));
  await expect(page.getByRole("heading", { name: "乙企业", exact: true })).toBeVisible();
  await expect(page.getByText("已收到您的咨询", { exact: true })).toHaveCount(0);
  await page.getByPlaceholder("请描述您的问题、影响和期望的处理结果").fill("你好乙企业");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect.poll(() => submitted).toEqual([companyA.id, companyB.id]);
  await page.goto("/staff/customers");
  await expect(page).toHaveURL(/\/staff\/login$/);
  await page.getByLabel("企业编号", { exact: true }).fill("alpha");
  await page.getByLabel("账号", { exact: true }).fill("agent");
  await page.locator('input[type="password"]').fill("staff-password-123");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "客户与会话" })).toBeVisible();
  await expect(page.getByText("甲企业", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "退出企业工作台" }).click();
  await expect(page).toHaveURL(/\/staff\/login$/);
  await page.goto("/customer/companies");
  await expect(page.getByRole("heading", { name: "选择您要咨询的企业" })).toBeVisible();
  await page.getByRole("button", { name: "退出客户账号" }).click();
  await expect(page).toHaveURL(/\/customer\/login$/);
});

test("登录失败给出明确反馈，不能进入企业工作台", async ({ page }) => {
  await page.route("**/api/v1/access/staff/login", (route) => route.fulfill({ status: 401, json: { detail: "账号、密码或企业编号不正确" } }));
  await page.goto("/staff/login");
  await page.getByLabel("企业编号", { exact: true }).fill("alpha");
  await page.getByLabel("账号", { exact: true }).fill("agent");
  await page.locator('input[type="password"]').fill("wrong-password-123");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByText("账号、密码或企业编号不正确", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/staff\/login$/);
});
