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
# 双入口使用说明

- `/customer/login`：客户账号注册和登录。
- `/customer/companies`：搜索并选择咨询企业。
- `/customer/companies/:companyId/chat`：与所选企业咨询、恢复该企业历史会话、自然语言建单。
- `/customer/tickets`：当前客户跨企业的个人工单，展示企业名称与进度，不包含内部备注。
- `/staff/login`：独立员工登录或创建新企业及首个员工账号，不能自行加入已有企业。
- `/staff/customers`：本企业的客户与关联会话、按客户进入工单处理。
- `/staff/tickets`：企业工单处理及关联会话只读查看。
- `/staff/agent-runs`：仅本企业运行记录。登录状态分别通过客户/员工 Cookie 验证。

Cookie 由后端维护，前后端请统一使用 `127.0.0.1`，不要混用 `localhost`。旧 `/tickets`、`/agent-runs` 地址会重定向到受保护的企业入口。

浏览器测试需先构建前端，再执行 `PLAYWRIGHT_CHANNEL=chrome pnpm test:e2e`（使用本机已安装 Chrome）。不设置该变量时使用 Playwright 的浏览器；如未安装，由使用者自行决定是否安装，脚本不会自动下载。
