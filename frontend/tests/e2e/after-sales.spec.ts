// 浏览器只替换 HTTP 边界，真实订单、检索、确认写入由后端集成测试覆盖。
import { expect, test } from "@playwright/test";

test("售后预判展示确认提示，客户确认后才显示已建单", async ({ page }) => {
  const id = "11111111-1111-4111-8111-111111111111";
  const companyId = "22222222-2222-4222-8222-222222222222";
  const requests: string[] = [];
  const history: object[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: object = [];
    if (path === "/api/v1/access/customer") body = { id, audience: "customer", display_name: "测试客户", company_id: null, company_name: null };
    else if (path === `/api/v1/customer/companies/${companyId}`) body = { id: companyId, name: "测试企业", code: "test" };
    else if (path.endsWith("/messages")) body = history;
    else if (path === "/api/v1/agent/chat") {
      requests.push(route.request().postDataJSON().message);
      const confirmed = requests.length === 2;
      const reply = confirmed ? "已为您创建退货工单。" : "无线键盘符合申请条件，回复“确认提交”创建售后工单，不代表退款获批。";
      const messageId = crypto.randomUUID();
      const tool = confirmed ? "create_order_ticket" : "search_company_knowledge";
      // 模拟服务端已保存的历史，避免轮询把刚收到的回复清空。
      history.push({ id: messageId, role: "agent", content: reply, created_at: "2026-09-30T00:00:00Z",
        tool_call: { name: tool, status: "success", ticket_code: confirmed ? "TK-TEST-001" : null } });
      body = {
        conversation_id: id, customer_message_id: crypto.randomUUID(), agent_message_id: messageId, agent_run_id: id, reply,
        intent: "order", priority: "medium", requires_human: false, reason: "售后预判",
        created_ticket_id: confirmed ? id : null, created_ticket_code: confirmed ? "TK-TEST-001" : null,
        executed_tool: tool,
      };
    }
    await route.fulfill({ json: body });
  });
  await page.goto(`/customer/companies/${companyId}/chat`);
  const input = page.getByPlaceholder("请描述您的问题、影响和期望的处理结果");
  await input.fill("我的无线键盘能退吗？可以的话帮我申请");
  await input.press("Enter");
  await expect(page.getByText(/符合申请条件/)).toBeVisible();
  await expect(page.getByText(/已创建，查看进度/)).toHaveCount(0);
  expect(requests).toHaveLength(1);
  await input.fill("确认提交");
  await input.press("Enter");
  await expect(page.getByText("已为您创建退货工单。", { exact: true })).toBeVisible();
  await expect(page.getByText(/已创建，查看进度/)).toBeVisible();
  expect(requests[1]).toBe("确认提交");
  await input.fill("谢谢");
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeEnabled();
});

test("企业运行详情展示工具执行顺序、状态与耗时", async ({ page }) => {
  const id = "11111111-1111-4111-8111-111111111111";
  const companyId = "22222222-2222-4222-8222-222222222222";
  const run = {
    id, request_id: "after-sales-test", conversation_id: id, ticket_id: id,
    status: "succeeded", model_name: "test", intent: "order", priority: "medium", requires_human: false,
    decision_reason: "售后预判完成", tool_name: "create_order_ticket", ticket_code: "TK-TEST-001",
    duration_ms: 50, error_type: null, error_message: null, started_at: "2026-09-30T00:00:00Z", completed_at: "2026-09-30T00:00:01Z",
    steps: ["query_my_orders", "search_company_knowledge", "create_order_ticket"].map(name => ({ name, kind: "tool", status: "succeeded", duration_ms: 10 })),
  };
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let body: object = [];
    if (path === "/api/v1/access/staff") body = { id, audience: "staff", display_name: "测试客服", company_id: companyId, company_name: "测试企业" };
    else if (path === "/api/v1/agent-runs") body = { items: [run], total: 1, offset: 0, limit: 10 };
    else if (path === "/api/v1/agent-runs/statistics") body = { total: 1, running: 0, succeeded: 1, failed: 0, tool_calls: 1, average_duration_ms: 50 };
    else if (path === `/api/v1/agent-runs/${id}`) body = run;
    await route.fulfill({ json: body });
  });
  await page.goto("/staff/agent-runs");
  await page.getByText("TK-TEST-001", { exact: true }).click();
  const steps = page.getByRole("list", { name: "执行步骤" }).getByRole("listitem");
  await expect(steps).toHaveCount(3);
  await expect(steps.nth(0)).toContainText("query_my_orders");
  await expect(steps.nth(1)).toContainText("search_company_knowledge");
  await expect(steps.nth(2)).toContainText("create_order_ticket · 成功 · 10 ms");
});
