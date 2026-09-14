# 后端服务

这里存放基于 FastAPI、LangChain 和 LangGraph 构建的智能客服后端服务。

计划包含以下模块：

- `app/api`：REST 接口和流式响应路由
- `app/schema`：按业务划分 HTTP 请求与响应模型，负责字段校验和接口数据协议
- `app/agent`：LangGraph 状态、节点、路由和流程构建
- `app/core`：配置、安全、日志及公共基础设施
- `app/db`：SQLAlchemy 模型、数据库会话和数据仓储
- `app/rag`：文档导入、知识检索、重排序和引用管理
- `app/services`：客户、订单、工单和人工审批服务
- `app/tools`：LangChain 工具及 MCP 适配器
- `tests`：单元测试、集成测试、Graph 测试、RAG 测试和效果评测

`app/schema/conversation.py` 定义聊天、消息历史及健康检查协议，`ticket.py` 定义工单协议，`agent_run.py` 定义运行记录协议。路由统一从这些模块导入。Agent 的模型输出协议继续放在 `app/agent/schemas.py`；数据库实体继续由 `app/db/models.py` 管理。调整目录不会改变接口 URL 或请求、响应字段。

## 当前最小 Agent

第一版已经实现“结构化分析 → 条件路由 → 自动回复或人工接管”的 LangGraph 工作流。模型负责输出意图、优先级和回复草稿，Graph 负责执行确定性的安全分支。

启动前请复制 `backend/.env.example` 为 `backend/.env`，并填写模型密钥。后端只读取后端目录中的配置，避免模型密钥进入前端构建产物。后端读取以下主要配置：

- `SUPPORT_MODEL_NAME`：当前使用 `deepseek-v4-flash`
- `SUPPORT_MODEL_API_KEY`：在 DeepSeek 开放平台申请的 API Key
- `SUPPORT_MODEL_BASE_URL`：DeepSeek 的 OpenAI 兼容地址 `https://api.deepseek.com`
- `SUPPORT_LOG_LEVEL`：应用日志等级，本地与生产默认使用 `INFO`

LangSmith 用于记录 LangChain/LangGraph 的模型调用和节点执行链路。填写 `LANGSMITH_API_KEY` 后，将 `LANGSMITH_TRACING` 改为 `true` 即可启用；`LANGSMITH_WORKSPACE_ID` 只在一个密钥关联多个 Workspace 时填写。

在已激活的项目虚拟环境中启动：

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

可用接口：

- `GET /health`：服务健康检查
- `POST /api/v1/agent/chat`：运行一次客服 Agent
- `GET /docs`：FastAPI 自动生成的接口文档

## 请求 ID 与结构化日志

每个 HTTP 响应都包含 `X-Request-ID`。调用方可以主动传入仅包含字母、数字、点、下划线、冒号或连字符的请求 ID；缺失或格式不安全时，后端会生成 UUID。

应用日志使用单行 JSON 输出。Agent 调用失败时，可用响应头中的请求 ID 检索 `agent_execution_failed` 事件，查看异常类型、上游状态码和服务端堆栈。日志不会记录客户消息正文、API Key 或模型供应商的完整响应体。
# 双入口权限边界

客户通过 `/api/v1/access/customer/register` 注册、`/customer/login`（同一 access 前缀）登录，获得客户专用数据库会话。员工使用 `/api/v1/access/staff/login`，提交企业编号、账号和密码；企业自助创建通过 `/staff/register-company`（同一前缀）完成，不会加入已有企业。两端凭证不可互换，退出会撤销对应数据库会话。

`/api/v1/tickets`、`/api/v1/staff/*` 与 `/api/v1/agent-runs` 的全部操作均从员工身份确定企业，列表、统计及读写都隔离。`/api/v1/customer/companies` 提供企业选择；客户聊天请求必须提供 `company_id`，但客户 ID 从登录会话提取。Tool 根据已验证的会话继承企业和客户归属，不允许模型设置。

迁移 `20260912_06` 建立账号及业务归属，`20260912_07` 添加数据库归属一致性约束。旧未归属记录仍保留，但普通新账号不能查看，不能自动认领。共享口令和访客 Cookie 已停用。

密码使用加盐 scrypt，昂贵计算隔离在线程池；数据库只存登录令牌摘要，八小时过期。认证接口每来源十分钟最多 30 次请求，使用数据库计数跨进程生效；不信任用户伪造的代理头。公开部署前需 HTTPS（`SUPPORT_COOKIE_SECURE=true`）、可信网关、账号恢复、员工管理和企业资质审核。

完整验证在本目录执行 `SUPPORT_TEST_DATABASE=1 ../.venv/bin/pytest -q`，真实数据库测试由外层事务回滚；模型使用固定输出，不消耗模型额度。
