// 只模拟接口边界，验证输入法、快捷键和欢迎语；不调用真实模型或创建工单。
import { expect, test } from "@playwright/test";

test("新会话介绍能力，Enter 发送且输入法和换行不误发", async ({ page }) => {
  const id = "11111111-1111-4111-8111-111111111111";
  const companyId = "22222222-2222-4222-8222-222222222222";
  const requests: string[] = [];
  let release: () => void = () => {};
  const waiting = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/agent/chat") {
      requests.push(route.request().postDataJSON().message);
      // 暂停响应，确认等待模型期间再次 Enter 不会产生重复请求。
      await waiting;
      await route.fulfill({ status: 503, json: { detail: "测试服务暂不可用" } });
      return;
    }
    let body: object = [];
    if (path === "/api/v1/access/customer") body = { id, audience: "customer", display_name: "测试客户", company_id: null, company_name: null };
    if (path === `/api/v1/customer/companies/${companyId}`) body = { id: companyId, name: "测试企业", code: "test" };
    await route.fulfill({ json: body });
  });
  await page.goto(`/customer/companies/${companyId}/chat`);
  const welcome = page.getByRole("article", { name: "客服自我介绍" });
  await expect(welcome).toContainText("我是测试企业的智能客服");
  for (const text of ["一、解答咨询", "二、查询订单", "三、创建工单", "四、跟进工单"]) {
    await expect(welcome).toContainText(text);
  }
  await page.getByRole("button", { name: "新建会话", exact: true }).click();
  await expect(welcome).toHaveCount(1);
  const input = page.getByPlaceholder("请描述您的问题、影响和期望的处理结果");
  await input.press("Enter");
  await input.fill("我的问题");
  await input.dispatchEvent("keydown", { key: "Enter", isComposing: true });
  await expect(input).toHaveValue("我的问题");
  await input.press("Shift+Enter");
  await input.press("End");
  await input.press("a");
  await expect(input).toHaveValue("我的问题\na");
  expect(requests).toHaveLength(0);
  await input.press("Enter");
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toBe("我的问题\na");
  await input.fill("下一条问题");
  await input.press("Enter");
  await expect(input).toHaveValue("下一条问题");
  expect(requests).toHaveLength(1);
  release();
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeEnabled();
});
