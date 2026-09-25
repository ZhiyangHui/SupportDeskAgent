// 浏览器验证分步跟进、修改回执与新字段；真实数据库流程由后端集成测试覆盖。
import { expect, test } from "@playwright/test";

test("跟进工单依次选择、编辑、确认，并显示修改后字段", async ({ page }) => {
  const id = "11111111-1111-4111-8111-111111111111";
  const companyId = "22222222-2222-4222-8222-222222222222";
  const code = "TK-EDIT-001";
  let step = 0;
  const requests: string[] = [];
  const replies = ["请选择要跟进的工单，回复序号：1. TK-EDIT-001｜客户希望退款｜待处理", "当前可修改信息：问题标题：客户希望退款；问题描述：设备故障；售后诉求：退款；影响说明：未填写", "拟修改内容：退款 → 维修。回复“确认修改”后提交。", "已修改工单 TK-EDIT-001，修改前后的记录已保存。"];
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: object = [];
    if (path === "/api/v1/access/customer") body = { id, audience: "customer", display_name: "测试客户", company_id: null, company_name: null };
    else if (path === `/api/v1/customer/companies/${companyId}`) body = { id: companyId, name: "测试企业", code: "test" };
    else if (path === "/api/v1/agent/chat") {
      requests.push(route.request().postDataJSON().message);
      step++;
      body = { conversation_id: id, customer_message_id: companyId, agent_message_id: id, agent_run_id: id, reply: replies[step - 1], intent: "ticket", priority: "medium", requires_human: false, reason: "跟进工单", created_ticket_id: null, created_ticket_code: null, executed_tool: step === 4 ? "update_support_ticket" : null, updated_ticket_code: step === 4 ? code : null };
    } else if (path.endsWith("/messages")) body = [{ id, role: "agent", content: replies[step - 1], created_at: "2026-09-18T00:00:00Z", tool_call: step === 4 ? { name: "update_support_ticket", status: "success", ticket_code: code } : null }];
    else if (path === "/api/v1/customer/tickets") body = { total: 1, items: [{ id, code, title: "客户希望退款", description: "设备故障", desired_resolution: "维修", impact_note: "每天无法使用", order: { code: "MO-09afc33989de5c8280f585a84e4352f3", product_name: "年度维护服务" }, status: "open", updated_at: "2026-09-18T00:00:00Z", company_id: companyId, company_name: "测试企业" }] };
    else if (path.endsWith("/comments")) body = [{ id, content: "售后诉求\n修改前：退款\n修改后：维修", created_at: "2026-09-18T00:00:00Z" }];
    await route.fulfill({ json: body });
  });
  await page.goto(`/customer/companies/${companyId}/chat`);
  const input = page.getByPlaceholder("请描述您的问题、影响和期望的处理结果");
  for (const [index, message] of ["帮我跟进工单", "1", "改成维修", "确认修改"].entries()) {
    await input.fill(message);
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await expect(page.getByText(replies[index]!, { exact: true })).toBeVisible();
    if (index < 3) await expect(page.getByRole("link", { name: /已修改，查看记录/ })).toHaveCount(0);
  }
  expect(requests).toEqual(["帮我跟进工单", "1", "改成维修", "确认修改"]);
  await page.getByRole("link", { name: `工单 ${code} 已修改，查看记录 →` }).click();
  const details = page.locator('.ticket-issue-details');
  const orderSummary = page.getByRole('region', { name: '关联订单（只读）' });
  await expect(orderSummary).toContainText('年度维护服务');
  await expect(orderSummary).toContainText('MO-09afc33989de5c8280f585a84e4352f3');
  await expect(details).not.toContainText('MO-');
  await expect(details.locator('dt')).toHaveText(['问题描述', '售后诉求', '影响／紧急情况说明']);
  await expect(details.locator('dd')).toHaveText(['设备故障', '维修', '每天无法使用']);
  const contact = page.getByRole('link', { name: '联系该企业', exact: true });
  const records = page.getByRole('button', { name: '查看修改与补充记录' });
  const contactBox = await contact.boundingBox();
  const recordsBox = await records.boundingBox();
  expect(contactBox?.height).toBe(recordsBox?.height);
  expect(contactBox?.y).toBe(recordsBox?.y);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(contact).toBeVisible();
  await expect(records).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole("button", { name: "查看修改与补充记录" }).click();
  await expect(page.getByRole("region", { name: "我的修改与补充记录" })).toContainText("修改前：退款");
  await page.screenshot({ path: '/tmp/supportdesk-ticket-layout.png', fullPage: true });
});
