// 回归截图中的文字竖排，并验证中屏图标栏和手机顶部菜单仍可访问。
import { test, expect } from "@playwright/test";

for (const width of [1280, 1000, 390]) {
  test(`企业导航在 ${width}px 下不挤压文字且操作可见`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route("**/api/v1/**", async (route) => {
      const identity = { id: "11111111-1111-4111-8111-111111111111", audience: "staff", display_name: "客服小陈", company_id: "22222222-2222-4222-8222-222222222222", company_name: "企业服务中心" };
      await route.fulfill({ json: route.request().url().endsWith("/access/staff") ? identity : [] });
    });
    await page.goto("/staff/customers");
    const navigation = page.getByRole("complementary", { name: "企业工作台导航" });
    await expect(navigation).toBeVisible();
    for (const name of ["客户与会话", "工单处理", "Agent 运行记录"]) {
      const link = navigation.getByRole("link", { name, exact: true });
      await expect(link).toBeVisible();
      const label = link.locator(".staff-menu-label");
      if (width === 1000) await expect(label).toBeHidden();
      else {
        await expect(label).toBeVisible();
        expect(await label.evaluate((element) => element.getBoundingClientRect().height)).toBeLessThanOrEqual(24);
      }
      expect(await link.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    }
    await expect(navigation.getByRole("button", { name: "退出企业工作台" })).toBeVisible();
    await expect(navigation.getByRole("link", { name: "打开客户入口" })).toBeVisible();
    if (width === 1280) await navigation.screenshot({ path: "test-results/staff-navigation.png" });
  });
}
