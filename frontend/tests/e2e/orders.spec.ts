// 订单页面交互用接口替身；默认订单和关联建单的真实 SQL 由后端集成测试验证。
import { test, expect } from "@playwright/test";

test("客户查看三个模拟订单并创建第四个", async ({ page }) => {
  page.on("pageerror", (error) => { throw error; });
  const companyId = "22222222-2222-4222-8222-222222222222";
  const customerId = "11111111-1111-4111-8111-111111111111";
  const orders = ["机械设备", "键盘", "维护服务"].map((name, i) => ({ id: `33333333-3333-4333-8333-33333333333${i}`, code: `MO-TEST-${i}`, product_name: name, amount: "99.00", status: "paid", created_at: "2026-09-15T00:00:00Z" }));
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: object = [];
    if (path === "/api/v1/access/customer") body = { id: customerId, audience: "customer", display_name: "测试客户", company_id: null, company_name: null };
    else if (path.endsWith("/orders")) {
      if (route.request().method() === "POST") {
        const input = route.request().postDataJSON() as { product_name: string; client_request_id: string };
        expect(input.client_request_id).toBeTruthy();
        const row = { ...orders[0]!, id: "44444444-4444-4444-8444-444444444444", product_name: input.product_name, code: "MO-NEW" };
        orders.push(row); await route.fulfill({ status: 201, json: row }); return;
      }
      body = { items: orders, total: orders.length };
    } else if (path.includes("/companies/")) body = { id: companyId, name: "演示企业", code: "demo" };
    await route.fulfill({ json: body });
  });
  await page.goto(`/customer/companies/${companyId}/orders`);
  await expect(page.getByText("共 3 单 · 第 1 页")).toBeVisible();
  await page.getByPlaceholder("例如：家用机械设备").fill("打印机");
  await page.getByRole("button", { name: "创建模拟订单", exact: true }).click();
  await expect(page.getByRole("heading", { name: "打印机", exact: true })).toBeVisible();
  await expect(page.getByText("共 4 单 · 第 1 页")).toBeVisible();
  await expect(page.getByRole("link", { name: "向 Agent 咨询订单或申请工单 →" })).toHaveAttribute("href", `/customer/companies/${companyId}/chat`);
});
