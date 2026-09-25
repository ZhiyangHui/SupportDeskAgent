// 校验补充工单的前后端协议和客户核对入口，不让追加记录被展示成新建成功。
import { expect, test } from "@playwright/test";

test("自然语言补充后显示独立标记，历史及工单页可核对记录", async ({ page }) => {
  const id = "11111111-1111-4111-8111-111111111111";
  const companyId = "22222222-2222-4222-8222-222222222222";
  const code = "TK-20260918-TEST";
  const reply = `已将补充信息记录到工单 ${code}，客服可在工单详情中查看。`;
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: object = [];
    if (path === "/api/v1/access/customer") body = { id, audience: "customer", display_name: "测试客户", company_id: null, company_name: null };
    else if (path === `/api/v1/customer/companies/${companyId}`) body = { id: companyId, name: "测试企业", code: "test" };
    else if (path === "/api/v1/customer/conversations") body = [{ id, customer_id: id, company_id: companyId, updated_at: "2026-09-18T00:00:00Z" }];
    else if (path === "/api/v1/agent/chat") body = { conversation_id: id, customer_message_id: companyId, agent_message_id: id, agent_run_id: id, reply, intent: "ticket", priority: "high", requires_human: false, reason: "补充工单", created_ticket_id: null, created_ticket_code: null, commented_ticket_code: code, executed_tool: "append_ticket_comment" };
    else if (path.endsWith("/messages")) body = [{ id, role: "agent", content: reply, created_at: "2026-09-18T00:00:00Z", tool_call: { name: "append_ticket_comment", status: "success", ticket_code: code } }];
    else if (path === "/api/v1/customer/tickets") body = { total: 1, items: [{ id, code, title: "设备维修", description: "原始问题", status: "open", updated_at: "2026-09-18T00:00:00Z", company_id: companyId, company_name: "测试企业" }] };
    else if (path.endsWith("/comments")) body = [{ id, content: "设备开机会冒烟", created_at: "2026-09-18T00:00:00Z" }];
    await route.fulfill({ json: body });
  });
  await page.goto(`/customer/companies/${companyId}/chat`);
  await page.getByPlaceholder("请描述您的问题、影响和期望的处理结果").fill(`给 ${code} 补充：设备开机会冒烟`);
  await page.getByRole("button", { name: "发送", exact: true }).click();
  const marker = page.getByRole("link", { name: `已补充到工单 ${code}，查看记录 →` });
  await expect(marker).toBeVisible();
  await expect(page.getByText(/已创建，查看进度/)).toHaveCount(0);
  await page.reload();
  await page.getByText("查看与该企业的历史会话", { exact: true }).click();
  await page.getByRole("button", { name: /11111111/ }).click();
  await expect(marker).toBeVisible();
  await marker.click();
  await page.getByRole("button", { name: "查看修改与补充记录" }).click();
  await expect(page.getByRole("region", { name: "我的修改与补充记录" })).toContainText("设备开机会冒烟");
});
