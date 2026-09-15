// 模拟网络边界验证查询标记；真实工具执行和客户/企业隔离由后端集成测试覆盖。
import { test, expect } from "@playwright/test";

test("查询结果显示只读工具标记，恢复历史时不误报建单", async ({ page }) => {
  const id = "11111111-1111-4111-8111-111111111111";
  const companyId = "22222222-2222-4222-8222-222222222222";
  const reply = "工单 TK-001 当前待处理。";
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: object = [];
    if (path === "/api/v1/access/customer") body = { id, audience: "customer", display_name: "测试客户", company_id: null, company_name: null };
    else if (path === `/api/v1/customer/companies/${companyId}`) body = { id: companyId, name: "测试企业", code: "test" };
    else if (path === "/api/v1/customer/conversations") body = [{ id, customer_id: id, updated_at: "2026-09-14T00:00:00Z", company_id: companyId }];
    else if (path === "/api/v1/agent/chat") body = { conversation_id: id, customer_message_id: companyId, agent_message_id: id, agent_run_id: id, reply, intent: "ticket", priority: "low", requires_human: false, reason: "查询工单", created_ticket_id: null, created_ticket_code: null, queried_tickets: true };
    else if (path.endsWith("/messages")) body = [{ id, role: "agent", content: reply, created_at: "2026-09-14T00:00:00Z", tool_call: { name: "query_support_tickets", status: "success", ticket_code: null } }];
    await route.fulfill({ json: body });
  });
  await page.goto(`/customer/companies/${companyId}/chat`);
  await page.getByPlaceholder("请描述您的问题、影响和期望的处理结果").fill("我的工单处理到哪了");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByText(reply, { exact: true })).toBeVisible();
  await expect(page.getByText("已查询当前企业的工单，查看我的工单 →")).toBeVisible();
  await expect(page.getByText(/已创建，查看进度/)).toHaveCount(0);
  // 重新进入页面，再主动恢复会话，验证持久化协议而不只验证即时响应。
  await page.reload();
  await page.getByText("查看与该企业的历史会话", { exact: true }).click();
  await page.getByRole("button", { name: /11111111/ }).click();
  await expect(page.getByText("已查询当前企业的工单，查看我的工单 →")).toBeVisible();
});
