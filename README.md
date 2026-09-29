# SupportDeskAgent
企业客服与工单处理 Agent。

客户与企业使用独立账号和登录会话，不再使用访客身份或共享企业口令。企业员工以“企业编号 + 账号 + 密码”登录；客户以“账号 + 密码”登录后选择要咨询的企业。旧 `SUPPORT_STAFF_ACCESS_KEY` 已不再读取，不能用于登录。

首次使用：先到企业登录页点击“创建新企业”，设置企业编号、名称和首个员工账号；再到客户登录页注册客户，登录后选择该企业咨询。创建企业不会加入任何已有企业。企业目录不代表资质认证。

每段会话和每张新工单同时归属企业与客户。客户仅能查看自己的记录，员工仅能查看本企业记录。旧数据保留在数据库中但不自动分配给任何新账号，需后续核实归属后迁移。前后端统一使用 `127.0.0.1`，不要和 `localhost` 混用。企业内员工管理、密码找回及企业资质审核尚未实现。

## 人工接管（最小版本）

1. 客户先向企业发送消息，建立会话。
2. 客户明确申请人工或 Agent 判断需要人工后，会话进入待接管队列。企业端“客户与会话”一级页面顶部直接展示待办，导航同时显示待接管数量。点击“立即接管并回复”即可打开回复窗口，不必先选择客户。
3. 接管后，客户继续使用原输入框发送消息；后端只保存消息，不调用模型、不执行 Agent 工具。客服在人工回复框中发送回复。
4. 当前接管客服点击“恢复智能客服”，AI 从客户下一条消息继续服务。

两端每 3 秒轮询消息和接管状态，并非 WebSocket 推送。工作区分为“待人工接管”和“我正在接待”，队列按申请时间排序、分页展示。只有当前接管客服可以回复和恢复，其他企业不可访问。排队期间 AI 仍可协助补充问题，实际接管后暂停；请求已提交不代表客服已接通。本版没有自动分配和客服离线自动释放。

队列字段由服务端持久化，刷新不会丢失。接管后会话从待办移入“我正在接待”，恢复 AI 后退出本次接管。迁移 `20260925_14` 会补录最近一次成功运行明确要求人工、且尚未被人工处理的旧会话，不根据聊天文本中的“转人工”字样猜测。

后端使用同一 PostgreSQL 会话锁串行处理 Agent、接管和人工回复。AI 正在处理时，接管返回忙碌提示，需要稍后重试，不强行中断已开始的工具。人工回复使用客户端请求标识防止重复发送。恢复 AI 会切换检查点代次，导入客户和人工聊天历史，不延续接管前未确认的工具状态；旧检查点保留，长期偏好不变。

新增入口：`app/api/handoff_routes.py`、`app/services/handoff_service.py`、`app/schema/handoff.py` 和前端 `HandoffControls.vue`。迁移为 `20260921_13`，启动脚本会自动执行。消息角色新增 `staff`，人工模式聊天回执的 `agent_message_id`、`agent_run_id` 为 `null`，不能把它当作模型回复。

## 企业知识库 RAG（第一版）

企业入口为 `/staff/knowledge`：录入文本或上传 UTF-8 的 TXT/Markdown，先保存草稿，再点击“建立索引并发布”。只上传允许本企业客户阅读的资料，不上传内部密钥、密码或保密文档。发布会将正文发送给配置的 Embedding 供应商；问答会将命中片段发送给聊天模型。

在 `backend/.env` 填写以下配置并重启后端：

```dotenv
# 独立于 DeepSeek 聊天模型，不能假设聊天接口支持 Embedding。
SUPPORT_KNOWLEDGE_ENABLED=true
SUPPORT_EMBEDDING_API_KEY=填写向量服务密钥
SUPPORT_EMBEDDING_BASE_URL=填写供应商的OpenAI兼容接口地址
SUPPORT_EMBEDDING_MODEL=填写向量模型名称
# 必须等于该模型实际返回的维度；系统不会自动给供应商发送 dimensions 参数。
SUPPORT_EMBEDDING_DIMENSIONS=1536
SUPPORT_KNOWLEDGE_MIN_SCORE=0.5
```

当前默认关闭、密钥留空。无需安装新服务；本次用到的 Python 包已在当前虚拟环境中存在，未安装依赖。`requirements.txt` 显式补充直接依赖 `langchain-text-splitters`。

处理链路：企业文档草稿 → 中文友好切分（700 字符、100 字符重叠）→ 独立向量模型 → PostgreSQL/pgvector → `search_company_knowledge` 只读 ToolNode → 模型依据片段生成结构化答案 → 程序校验来源序号并附原文摘录。企业政策问答由意图节点路由到独立知识分支，订单查询、建单、修改工单和人工接管仍保留原流程。

边界与使用说明：

- 正文最多 60000 字符，文件最多 240 KB，最多 150 个切片；第一版不支持 PDF/OCR、网页抓取和后台大文件任务。
- 文档发布与向量替换在同一事务提交；向量接口失败时不破坏旧索引。停用后新的检索不再返回该文档，已有聊天中的历史引用不会删除。
- 每次查询在 SQL 层按企业、发布状态和向量模型指纹过滤；改变模型、接口地址或维度后，需要在企业页面重新建立索引，不能混用不同模型的向量。
- 第一版采用精确向量检索，不包含 BM25 混合检索、重排或知识图谱。相似度阈值不是正确率，应使用真实业务问题调优。
- 没有命中、不相关或引用序号无效时不输出企业政策结论。来源以数据库真实文档和片段为准。提示词将资料视为不可信数据，知识分支没有任何写工具；这不等于模型回答已获得事实正确性的数学保证。
- 检索测试与发布会产生供应商 API 请求；开发验证仅使用模型替身，不调用真实付费 API。配置完成后应先发布一份合成测试政策，再问同企业与不同企业的问题进行人工验收。
- 核心文件为 `db/knowledge_models.py`、`schema/knowledge.py`、`services/knowledge_service.py`、`api/knowledge_routes.py`、`agent/workflows/knowledge_workflow.py`。迁移版本为 `20260925_15`。

实现参考：[LangChain Embeddings 官方接口](https://reference.langchain.com/python/langchain-openai/embeddings/base/OpenAIEmbeddings)、[pgvector Python 官方 SQLAlchemy 用法](https://github.com/pgvector/pgvector-python)。使用现有 LangGraph 图和 ToolNode，不引入另一套 Agent 框架。

## 一键启动本地开发环境

首次准备好项目 `.venv`、前端 `node_modules`、`backend/.env` 和 `frontend/.env.local` 后，在项目根目录执行：

```bash
bash scripts/start.sh
```

脚本自动打开 macOS Docker Desktop、等待 PostgreSQL 健康、执行 Alembic 迁移，并启动支持热更新的后端和前端。无需手动激活虚拟环境；不会安装或升级任何依赖。前端直接运行 pnpm 已安装的本地 Vite，避免包管理器在启动时触发隐式下载。

- 客户入口：http://127.0.0.1:3000/customer/login
- 企业入口：http://127.0.0.1:3000/staff/login
- 接口文档：http://127.0.0.1:8000/docs
- 只检查启动条件：`bash scripts/start.sh --check`
- 查看日志：`tail -f logs/backend.log logs/frontend.log`

保持启动终端打开，按 `Ctrl+C` 统一停止本次启动的前后端。数据库容器保持运行，若也要停止数据库，在项目根目录执行 `docker compose stop postgres`（数据卷保留）。

如果提示 3000 或 8000 端口被占用，请先在此前启动服务的终端按 `Ctrl+C`，再执行脚本。脚本不会停止其他终端的服务。该入口用于本地开发，使用 `backend/.env` 中的数据库配置执行迁移。

端口预检使用地址复用并实际验证监听，避免把服务退出后的 TIME_WAIT 误判为残留进程；不会启用共享监听或自动杀进程。若仍提示无法监听，可执行 `lsof -nP -iTCP:3000`（后端改为 8000）检查全部相关连接。预检结束到服务启动之间仍可能有其他程序抢占端口，最终以启动健康检查为准。

## Agent 记忆管理

Agent 目录分为两组：`backend/app/agent/memory/` 保存订单/修改工单状态、模型上下文裁剪与 PostgreSQL 持久化资源；`backend/app/agent/workflows/` 保存订单处理和修改工单的流程节点。`graph.py` 继续负责连接节点，`tools.py` 定义工具，业务写入仍在 Service 层。

旧位置的 `order_memory.py` 和 `comment_memory.py` 仅保留历史检查点的导入兼容入口，没有业务实现；新代码统一从 `memory/` 导入。不能直接删除这两个入口，否则旧会话中记录的模块路径无法恢复。该重构不删除检查点，不需要数据库迁移。

- 短期记忆采用官方 `AsyncPostgresSaver`，按企业、客户和会话生成可信 `thread_id`，保存消息、工具结果及售后流程状态。重启后可继续未完成的正常多轮对话。
- 长期记忆采用官方 `AsyncPostgresStore`，按企业和客户隔离。当前只保存客户显式设置的回复偏好，不自动提取聊天中的个人信息，不把订单和工单复制进记忆。
- 应用启动时使用库提供的 `setup()` 初始化或升级记忆表，连接池随应用关闭。记忆表迁移由官方组件管理，业务表仍由 Alembic 管理。沿用 `SUPPORT_DATABASE_URL`，不需新增密钥。
- 历史会话在没有检查点时导入一次；业务消息表继续用于页面与审计，不再持续写入流程快照。每轮只追加当前输入，避免历史消息重复。

客户登录后可以通过接口文档使用 `GET / PUT / DELETE /api/v1/customer/companies/{company_id}/preferences` 读取、保存、清除偏好。PUT 请求体为 `{"reply_style":"detailed"}` 或 `{"reply_style":"concise"}`，目前尚无对应前端设置页面。偏好影响模型生成的解释，不改变固定业务确认消息。

同一会话的并发消息返回 409。未完成检查点不会在新消息中盲目恢复：如果返回 `checkpoint_recovery_required`，先按请求 ID 核对运行日志和工单回执；当前未提供自动恢复或删除检查点按钮，不能通过直接重放工具解决。正常结束的多轮对话不受影响。记忆数据库与业务事务并非一个原子事务，副作用仍依赖业务幂等机制。

官方依据：[LangGraph 记忆指南](https://docs.langchain.com/oss/python/langgraph/add-memory)。后续相关改动需先核对官方文档及已安装版本。

## 用自然语言跟进和修改工单

客户说“帮我跟进工单”或“修改工单”后，依次执行以下步骤：

1. 展示编号、标题、状态，客户回复序号或完整编号选择。只有一条匹配也必须选择；直接给编号也先展示候选让客户确认。
2. 展示四个可编辑字段：问题标题、问题描述、售后诉求、影响／紧急情况说明。未填写的新字段显示“未填写”，不从旧描述猜测并回填。
3. 客户说明修改内容，例如“把售后诉求改成维修”。未提及字段保持原值，空标题/描述会被拒绝。
4. 展示修改前后预览；客户回复“确认修改”才提交，也可继续更正或“取消修改”。改草稿、换工单和版本变化都会撤销旧确认。

实现入口为 `memory/ticket_edit_memory.py` 和 `workflows/ticket_edit_workflow.py`；模型只提取 `edit_turn`，程序管理阶段和候选顺序。实际执行的是 `update_support_ticket`，经官方 ToolNode 注入可信身份，Service 锁定请求与工单并核对版本，再原子保存字段、审计和 `update_activity_id` 回执。只读工单查询仍保持独立分支。

客户只能修改自己在当前企业的工单，已关闭工单拒绝修改。状态、负责人、系统优先级、关联订单和企业归属不允许修改；影响说明不自动升级系统优先级。旧描述的历史值保存在审计中，不执行其中指令，也不触发实际退款。

企业详情展示新字段和修改时间线；客户可在“我的工单 → 查看修改与补充记录”核对自己的记录，内部备注不公开。同键重试只返回原结果；若已修改但回复失败，返回 `outcome=ticket_updated`。预览后工单版本改变时不会覆盖，需查看最新值再确认。

旧 `append_ticket_comment` 工具及执行分支已撤下；旧补充记录、响应协议和检查点类型保留兼容。旧补充草稿不会自动转换为已确认修改，请重新说“跟进工单”。未完成检查点仍需先核对副作用，不能自动重放。

新增业务迁移 `20260918_11`，一键启动会自动执行；手动启动先在 backend 运行 `../.venv/bin/alembic upgrade head` 再重启。无需新增依赖或密钥。官方机制参考：[LangChain Tools](https://docs.langchain.com/oss/python/langchain/tools)。
