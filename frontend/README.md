# 前端应用

这里存放基于 Vue 3、TypeScript 和 Vite 构建的客户聊天页面与客服工作台。

计划包含以下模块：

- `src/views`：由 Vue Router 管理的页面
- `src/components`：通用组件及客服工作台组件
- `src/lib`：API 客户端、SSE 客户端、数据校验和工具函数
- `src/stores`：Pinia 客户端状态管理
- `src/types`：前端领域类型
- `tests`：Playwright 端到端测试

服务端状态由 TanStack Query 管理，跨组件客户端状态由 Pinia 管理，通用后台组件使用 Element Plus。
