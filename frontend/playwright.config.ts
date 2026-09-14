// 浏览器测试使用独立预览端口和模拟接口，不连接用户正在运行的业务服务。
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  // 可指定本机已有 Chrome，避免测试时自动下载浏览器；仍使用隔离临时配置，不访问个人资料。
  use: { baseURL: "http://127.0.0.1:3101", headless: true, channel: process.env.PLAYWRIGHT_CHANNEL },
  webServer: {
    command: "node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 3101 --strictPort",
    url: "http://127.0.0.1:3101", reuseExistingServer: false,
  },
});
