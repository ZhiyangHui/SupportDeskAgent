// 错误接口使用确定性替身，验证用户反馈与幂等键，而非只检查页面是否弹出提示。
import { test, expect } from "@playwright/test";

for (const outcome of ["unknown", "not_executed", "ticket_created"] as const) {
  test(`Agent 错误反馈区分 ${outcome}`, async ({ page }) => {
    const id = "11111111-1111-4111-8111-111111111111";
    const companyId = "22222222-2222-4222-8222-222222222222";
    const keys: string[] = [];
    await page.route("**/api/v1/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      let body: object = [];
      if (path === "/api/v1/access/customer") body = { id, audience: "customer", display_name: "测试客户", company_id: null, company_name: null };
      else if (path === `/api/v1/customer/companies/${companyId}`) body = { id: companyId, name: "测试企业", code: "test" };
      else if (path === "/api/v1/agent/chat") {
        keys.push((route.request().postDataJSON() as { client_request_id: string }).client_request_id);
        await route.fulfill({ status: 502, json: { detail: {
          code: "agent_failed", message: outcome === "ticket_created" ? "工单 TK-001 已创建，请勿重复提交。" : "本次服务暂时不可用。",
          request_id: "test-request-001", outcome, retryable: outcome === "not_executed",
          ticket_code: outcome === "ticket_created" ? "TK-001" : null,
        } } });
        return;
      }
      await route.fulfill({ json: body });
    });
    await page.goto(`/customer/companies/${companyId}/chat`);
    const input = page.getByPlaceholder("请描述您的问题、影响和期望的处理结果");
    await input.fill("请为登录故障建单");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await expect(page.getByText(/请求 ID：test-request-001/)).toBeVisible();
    if (outcome === "ticket_created") {
      await expect(input).toHaveValue("");
      await expect(page.getByText(/工单 TK-001 已创建/)).toBeVisible();
    } else {
      await expect(input).toHaveValue("请为登录故障建单");
      await page.getByRole("button", { name: "发送", exact: true }).click();
      await expect.poll(() => keys.length).toBe(2);
      expect(keys[0] === keys[1]).toBe(outcome === "unknown");
    }
  });
}
