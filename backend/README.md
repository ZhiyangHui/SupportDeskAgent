# 后端服务

这里存放基于 FastAPI、LangChain 和 LangGraph 构建的智能客服后端服务。

计划包含以下模块：

- `app/api`：REST 接口和流式响应路由
- `app/agent`：LangGraph 状态、节点、路由和流程构建
- `app/core`：配置、安全、日志及公共基础设施
- `app/db`：SQLAlchemy 模型、数据库会话和数据仓储
- `app/rag`：文档导入、知识检索、重排序和引用管理
- `app/services`：客户、订单、工单和人工审批服务
- `app/tools`：LangChain 工具及 MCP 适配器
- `tests`：单元测试、集成测试、Graph 测试、RAG 测试和效果评测

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
