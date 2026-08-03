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
