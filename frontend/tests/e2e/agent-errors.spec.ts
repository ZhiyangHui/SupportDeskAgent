// 错误接口使用确定性替身，验证用户反馈与幂等键，而非只检查页面是否弹出提示。
import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { agentChatResponseSchema } from "../../src/types/agent";

test("普通聊天的后端响应和历史回执能通过前端校验并展示", async ({ page }) => {
  // 使用后端真实 Pydantic 协议生成响应，避免手写前端 mock 掩盖空字符串契约问题。
  // 只运行项目已有虚拟环境，不安装依赖，也不调用真实模型。
  const payload: unknown = JSON.parse(execFileSync(resolve("../.venv/bin/python"), ["-c", `
from app.schema.conversation import ChatResponse
from tests.test_chat_response_contract import response_payload
print(ChatResponse.model_validate(response_payload("")).model_dump_json())
`], { cwd: resolve("../backend"), encoding: "utf8" }));
  const response = agentChatResponseSchema.parse(payload);
  expect(response.executed_tool).toBeNull();
  const companyId = "22222222-2222-4222-8222-222222222222";
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: object = [];
    if (path === "/api/v1/access/customer") body = { id: response.customer_message_id, audience: "customer", display_name: "测试客户", company_id: null, company_name: null };
    else if (path === `/api/v1/customer/companies/${companyId}`) body = { id: companyId, name: "测试企业", code: "test" };
    else if (path === "/api/v1/agent/chat") body = response;
    else if (path.endsWith("/messages")) body = [{ id: response.agent_message_id, role: "agent", content: response.reply, created_at: "2026-09-16T11:59:31Z", tool_call: null }];
    await route.fulfill({ json: body });
  });
  await page.goto(`/customer/companies/${companyId}/chat`);
  const input = page.getByPlaceholder("请描述您的问题、影响和期望的处理结果");
  await input.fill("你好我姓王");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByText("王先生您好。", { exact: true })).toBeVisible();
  await expect(page.getByText(/暂时无法确认请求结果/)).toHaveCount(0);
  await expect(input).toHaveValue("");
});

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
