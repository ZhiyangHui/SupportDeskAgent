// Vite 配置集中管理 Vue 编译、组件按需导入、源码别名和本地开发端口。
import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import AutoImport from "unplugin-auto-import/vite";
import Components from "unplugin-vue-components/vite";
import { ElementPlusResolver } from "unplugin-vue-components/resolvers";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [
    // 负责解析单文件组件中的 template、script setup 和 scoped style。
    vue(),
    // 自动导入 Element Plus 的组合式 API，并生成声明文件维持 TypeScript 类型安全。
    AutoImport({
      resolvers: [ElementPlusResolver()],
      dts: "src/auto-imports.d.ts",
    }),
    // 模板中出现 el-button 等组件时按需引入实现和样式，避免全量打包 Element Plus。
    Components({
      resolvers: [ElementPlusResolver()],
      dts: "src/components.d.ts",
    }),
  ],
  resolve: {
    alias: {
      // 统一使用 @ 指向源码目录，目录调整时只需要维护这一处映射。
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    // 与项目约定的本地访问地址保持一致，便于后端 CORS 和代理配置长期固定。
    port: 3000,
  },
});
