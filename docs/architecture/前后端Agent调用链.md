# SupportDeskAgent 前后端调用链

## 1. 文档目的

本文按照当前项目代码的真实执行顺序，说明一条客户消息如何从 Vue 页面进入 FastAPI，经由 LangChain、DeepSeek 和 LangGraph 处理，再返回页面。

这里需要先区分五个容易混淆的概念：

| 概念 | 当前实现 | 职责 |
|---|---|---|
| API Schema | Pydantic `ChatRequest`、`ChatResponse` | 约束 HTTP 请求和响应 |
| Agent Schema | Pydantic `AgentDecision` | 约束大模型必须产出的结构化判断 |
| Graph State | `SupportAgentState` | 保存一次 LangGraph 运行中的临时状态 |
| Model | `ChatOpenAI` 适配的 DeepSeek V4 Flash | 完成自然语言理解和结构化推理 |
| Agent / Graph | 编译后的 LangGraph | 编排模型分析、条件路由和最终回复 |

前端还有一份 Zod Schema。它不是后端 Schema 的替代品，而是浏览器对外部响应进行的第二次运行时校验。

## 2. 总体结构

```text
Vue 页面
  │
  ├─ Pinia：草稿与消息列表
  ├─ TanStack Query：请求生命周期
  ├─ Agent Service：业务接口封装
  ├─ Axios：HTTP 客户端
  └─ Zod：响应校验
        │
        ▼
POST /api/v1/agent/chat
        │
        ▼
FastAPI Route
  ├─ ChatRequest：校验请求
  ├─ get_support_graph()：取得已缓存 Graph
  └─ ChatResponse：收敛响应
        │
        ▼
LangGraph
  ├─ analyze_request：调用结构化 Model
  ├─ choose_route：根据 requires_human 路由
  ├─ automatic_reply：自动回复
  └─ human_handoff：人工接管回复
        │
        ▼
DeepSeek V4 Flash
```

## 3. 后端启动与对象装配

### 3.1 FastAPI 应用入口

文件：`backend/app/main.py`

`create_app()` 创建 FastAPI 实例，读取应用名称、版本和调试配置，注册 CORS 中间件，然后挂载 API Router。

这里不创建模型，也不编译 Graph。这样做有两个原因：

1. 健康检查不应因为模型配置缺失而无法启动；
2. 测试可以创建相互隔离的 FastAPI 应用实例。

`CORSMiddleware` 只解决浏览器跨域访问，不负责认证和权限控制。

### 3.2 配置加载

文件：`backend/app/core/config.py`

`Settings` 使用 Pydantic Settings 从 `backend/.env` 读取配置，核心字段包括：

- `SUPPORT_MODEL_NAME`：模型 ID；
- `SUPPORT_MODEL_API_KEY`：DeepSeek API Key；
- `SUPPORT_MODEL_BASE_URL`：模型服务地址；
- `SUPPORT_CORS_ORIGINS`：允许访问后端的前端来源；
- `LANGSMITH_*`：LangSmith 追踪配置。

`get_settings()` 使用 `@lru_cache` 复用同一个配置实例，避免每个请求都重新读取环境文件。

`configure_langsmith_environment()` 把经过校验的配置同步到 LangChain 使用的标准环境变量。必须在创建模型和 Graph 之前调用，否则 LangSmith 回调可能读取不到正确配置。

## 4. 后端三类 Schema

### 4.1 HTTP 请求 Schema

文件：`backend/app/api/schemas.py`

```python
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
```

它位于 API 层，只描述浏览器能够提交什么。FastAPI 会在进入路由函数前自动校验：

- 缺少 `message`：返回 422；
- 不是字符串：返回 422；
- 空字符串或超过 4000 字符：返回 422。

### 4.2 模型结构化输出 Schema

文件：`backend/app/agent/schemas.py`

`AgentDecision` 约束模型分析结果：

```text
intent          问题意图
priority        处理优先级
requires_human  是否必须转人工
reason          判断理由
reply           回复草稿
```

其中 `SupportIntent` 和 `TicketPriority` 使用固定枚举，防止模型随意返回“比较紧急”“账号类问题”等无法稳定驱动程序的文本。

这份 Schema 服务于模型和 Graph，不直接等同于 HTTP 响应。模型返回 `reply`，Graph 最终对外返回的是经过路由处理的 `final_reply`。

### 4.3 HTTP 响应 Schema

文件：`backend/app/api/schemas.py`

`ChatResponse` 是后端承诺给前端的稳定契约：

```text
reply
intent
priority
requires_human
reason
```

它隔离了 LangGraph 内部字段。例如内部状态使用 `decision_reason` 和 `final_reply`，但前端只看到更稳定、简洁的 `reason` 和 `reply`。以后重构 Graph State 时，只要 API Schema 不变，前端就不需要跟着修改。

## 5. Model 与结构化输出封装

文件：`backend/app/agent/factory.py`

### 5.1 创建 Model 适配器

`ChatOpenAI` 在这里不是指项目调用了 OpenAI 模型，而是使用 OpenAI-compatible 协议访问 DeepSeek：

```python
model = ChatOpenAI(
    model=settings.model_name,
    api_key=settings.model_api_key,
    base_url=settings.model_base_url,
    temperature=0,
    extra_body={"thinking": {"type": "disabled"}},
)
```

各参数的作用：

- `model`：当前为 `deepseek-v4-flash`；
- `api_key`：服务端密钥，只存在于后端；
- `base_url`：将请求发送到 DeepSeek，而不是 OpenAI；
- `temperature=0`：降低同类输入的输出波动；
- `thinking=disabled`：关闭 DeepSeek V4 默认思考模式，以兼容当前强制 Function Calling。

### 5.2 封装结构化 Model

```python
decision_model = model.with_structured_output(
    AgentDecision,
    method="function_calling",
)
```

这一步把通用聊天模型包装成“只能产出 `AgentDecision` 的模型”。LangChain 将 Pydantic Schema 转换成 Function Calling 描述，DeepSeek 返回结构化参数，随后再由 Pydantic 校验并生成 `AgentDecision` 对象。

Function Calling 在这里用于约束结构化输出，不代表系统已经调用了订单、退款等真实业务工具。

必须显式指定 `method="function_calling"`。如果使用当前 `ChatOpenAI` 的默认结构化输出方式，DeepSeek 会拒绝不兼容的 `response_format`。

### 5.3 Factory 为什么缓存 Graph

`get_support_graph()` 使用 `@lru_cache`：

- 第一次聊天请求时创建 Model、包装结构化输出并编译 Graph；
- 后续请求复用同一个已编译 Graph；
- 避免每次请求重复完成对象装配。

因此修改模型或 Graph 配置后应重启后端，确保缓存实例被重新创建。

## 6. LangGraph State 与节点编排

### 6.1 Graph State

文件：`backend/app/agent/state.py`

`SupportAgentState` 继承 `MessagesState`，包含消息列表以及本次运行需要的临时字段：

```text
messages         当前 Graph 使用的消息
intent           模型识别的意图
priority         模型判断的优先级
requires_human   路由依据
decision_reason  内部判断理由
reply_draft      模型生成的回复草稿
final_reply      路由节点生成的最终回复
```

State 只服务于一次工作流运行，不负责持久化客户、工单或长期会话历史。长期数据以后应进入 PostgreSQL，而不是不断扩充 Graph State。

### 6.2 `analyze_request` 节点

文件：`backend/app/agent/graph.py`

该节点把系统提示词放在消息首部，再调用 `decision_model.ainvoke()`：

```text
SystemMessage(SYSTEM_PROMPT)
        +
state["messages"]
        ↓
DeepSeek
        ↓
AgentDecision
```

它把 `AgentDecision` 映射进 Graph State，但不直接决定最终输出。模型负责理解自然语言，Graph 负责执行可审计的业务路由。

### 6.3 `choose_route` 条件路由

```text
requires_human = false → automatic_reply
requires_human = true  → human_handoff
```

路由条件写在确定性的 Python 代码中，而不是让回复节点自由决定。这样，高风险请求必须转人工的规则更清晰，也更容易进行单元测试和审计。

### 6.4 回复节点

`automatic_reply` 直接采用模型的 `reply_draft`，并写入：

- `final_reply`：供 API 层读取；
- `messages`：追加 `AIMessage`，保持消息状态完整。

`human_handoff` 在草稿后补充人工接管说明。它只承诺“转交核验”，不会声称退款、删除数据等高风险操作已经执行。

### 6.5 Graph 拓扑

```text
START
  ↓
analyze_request
  ↓
choose_route
  ├─ automatic_reply ─→ END
  └─ human_handoff  ─→ END
```

`build_support_graph()` 最后调用 `compile()`，把节点与边编译成可以执行的 Graph。

## 7. FastAPI 请求执行流程

文件：`backend/app/api/routes.py`

一次 `POST /api/v1/agent/chat` 按以下顺序执行：

1. FastAPI 使用 `ChatRequest` 校验 JSON 请求体；
2. 路由把字符串转换为 LangChain `HumanMessage`；
3. `get_support_graph()` 返回缓存的已编译 Graph；
4. `graph.ainvoke()` 异步运行完整工作流；
5. Graph 返回最终 State；
6. 路由从 State 中选取公开字段，构造 `ChatResponse`；
7. FastAPI 序列化响应并返回浏览器。

字段映射如下：

| Graph State | HTTP Response |
|---|---|
| `final_reply` | `reply` |
| `intent` | `intent` |
| `priority` | `priority` |
| `requires_human` | `requires_human` |
| `decision_reason` | `reason` |

异常边界：

- 缺少模型 Key：转换为 503；
- 模型调用、结构化解析或 Graph 执行异常：统一转换为 502；
- 供应商原始异常不会直接返回前端，避免泄露内部信息。

当前不足是通用异常尚未写入结构化日志，因此页面只能看到统一错误。后续应记录异常类型、请求 ID、Graph 节点和供应商状态码，但不能记录 API Key 或敏感客户数据。

## 8. 前端基础设施装配

文件：`frontend/src/main.ts`

应用挂载前注册三个基础设施：

- Pinia：管理浏览器端共享状态；
- Vue Router：管理页面路由；
- Vue Query：管理服务端请求和缓存状态。

`useMutation()` 依赖 `VueQueryPlugin` 提供的上下文，因此必须在 `app.mount()` 前注册。

## 9. 前端 API 封装链路

### 9.1 Zod 响应 Schema

文件：`frontend/src/types/agent.ts`

`agentChatResponseSchema` 与后端 `ChatResponse` 字段保持一致：

```text
reply
intent
priority
requires_human
reason
```

TypeScript 类型只约束编译期代码，不能证明网络响应真实可靠。因此前端通过 Zod 在运行时再次验证响应。

字段名必须完全一致。例如把 `priority` 写成 `ticketPriority`，TypeScript 仍可能通过，但 Zod 会拒绝后端响应，Mutation 随后进入错误状态。

`AgentChatResponse` 通过 `z.infer` 从 Schema 推导，避免同时手写 TypeScript Interface 和 Zod Schema 后发生漂移。

### 9.2 Axios 客户端

文件：`frontend/src/lib/http.ts`

`httpClient` 集中维护：

- `VITE_API_BASE_URL`；
- 60 秒请求超时；
- JSON 请求头。

该层不知道 Agent 接口路径，也不维护页面状态。以后工单、客户和知识库 Service 都可以复用同一个客户端。

`VITE_API_BASE_URL` 是公开的后端地址，可以进入浏览器；DeepSeek API Key 绝不能以 `VITE_` 变量形式放在前端。

### 9.3 Agent Service

文件：`frontend/src/services/agent-service.ts`

`sendAgentMessage()` 是前端 Agent API 边界：

1. 使用 `httpClient.post()` 发送 `{ message }`；
2. Axios 返回的数据先视为 `unknown`；
3. 使用 `agentChatResponseSchema.parse()` 校验；
4. 返回可信的 `AgentChatResponse`。

Service 知道接口路径和数据契约，但不知道 Pinia、按钮、消息列表或 Element Plus。

## 10. 前端状态与调用编排

### 10.1 Pinia 会话 Store

文件：`frontend/src/stores/conversation.ts`

Store 管理：

- `draft`：当前输入草稿；
- `messages`：页面显示的消息；
- `canSend`：草稿是否有效；
- 草稿读取、失败恢复和消息追加动作。

关键动作：

- `takeDraft()`：裁剪空白、清空输入框并返回本次请求快照；
- `appendCustomerMessage()`：立即显示客户消息；
- `appendAgentMessage()`：成功后显示 Agent 回复；
- `restoreDraft()`：失败时恢复原文，但不覆盖用户等待期间输入的新内容。

Store 不直接调用 Axios，因为 HTTP 请求的加载、错误和生命周期属于 TanStack Query。

### 10.2 TanStack Query Composable

文件：`frontend/src/composables/useAgentChat.ts`

`useAgentChat()` 是前端调用链的编排层：

```text
submitDraft()
  ↓
检查 isPending，阻止重复提交
  ↓
conversationStore.takeDraft()
  ↓
立即 appendCustomerMessage()
  ↓
mutation.mutate(content)
  ↓
sendAgentMessage(content)
```

成功时：

```text
Service 返回通过 Zod 校验的数据
  ↓
onSuccess(response)
  ↓
appendAgentMessage(response.reply)
```

失败时：

```text
Axios、HTTP 或 Zod 抛出异常
  ↓
onError(error, submittedContent)
  ↓
restoreDraft(submittedContent)
  ↓
页面通过 error 显示统一提示
```

客户消息在请求发出前就进入列表，所以失败后仍能看到已发送内容。草稿恢复用于方便修改后重试。

### 10.3 Vue 页面组件

文件：`frontend/src/components/SupportWorkspace.vue`

页面通过 `storeToRefs()` 读取响应式的 `messages`、`draft` 和 `canSend`，通过 `useAgentChat()` 取得：

- `submitDraft`：提交入口；
- `isPending`：加载状态；
- `error`：错误状态。

`canSubmit` 同时要求草稿有效且当前无请求：

```text
canSend && !isPending
```

表单只调用 `submitDraft`，按钮根据 `isPending` 显示加载状态，`el-alert` 根据 `error` 显示统一错误。组件不直接使用 Axios，也不解析响应结构。

## 11. 一次完整请求的时序

```text
1. 用户在 textarea 输入问题
2. v-model 把内容同步到 Pinia draft
3. 表单触发 submitDraft()
4. Store 取出草稿并立即追加客户消息
5. Mutation 调用 Agent Service
6. Service 通过 Axios POST 请求
7. FastAPI 用 ChatRequest 校验请求
8. Route 把 message 转成 HumanMessage
9. Factory 返回缓存的 LangGraph
10. analyze_request 调用 DeepSeek 结构化 Model
11. Pydantic 将模型输出校验为 AgentDecision
12. Graph 根据 requires_human 选择回复节点
13. 回复节点写入 final_reply
14. Route 将 Graph State 映射成 ChatResponse
15. Axios 收到 JSON
16. Zod 校验为 AgentChatResponse
17. Mutation onSuccess 追加 Agent 消息
18. Vue 响应式更新页面
```

## 12. Schema 一致性原则

当前跨层契约关系如下：

```text
后端 ChatRequest.message
          ↑
前端 Service 请求体 { message }

后端 ChatResponse
          ↓ 字段必须一致
前端 agentChatResponseSchema

后端 AgentDecision
          ↓ 节点映射
LangGraph SupportAgentState
          ↓ Route 映射
后端 ChatResponse
```

修改字段时不能只改一层。例如修改 `requires_human`，至少需要检查：

1. `AgentDecision`；
2. `SupportAgentState`；
3. Graph 节点和条件路由；
4. `ChatResponse` 与 Route 映射；
5. 前端 Zod Schema；
6. 使用该字段的页面或状态逻辑；
7. 对应单元测试和集成测试。

## 13. 当前边界与下一步

当前实现完成的是单轮、非流式、无持久化的最小 Agent 链路：

- 每次请求只传当前一条用户消息；
- Graph State 仅在本次调用内存在；
- 前端消息只保存在浏览器内存；
- 尚未接入 RAG、真实业务 Tool、Checkpoint 和数据库；
- “人工接管”当前只是回复文案，没有真正创建工单或通知客服。

后续合理演进顺序：

1. 增加结构化日志和请求 ID，提升 502 排错能力；
2. 引入会话 ID、PostgreSQL 消息持久化和 LangGraph Checkpoint；
3. 接入可评测的 RAG；
4. 增加订单、账号和工单 Tool Calling；
5. 为高风险工具加入 Human-in-the-loop；
6. 实现 SSE 流式回复；
7. 补充关键链路集成测试和端到端测试。

这套分层的核心不是增加文件数量，而是让每一层只承担一种变化：模型供应商变化影响适配层，工作流变化影响 Graph，HTTP 契约变化影响 API Schema，页面交互变化影响组件，而共享状态和请求状态分别由 Pinia 与 TanStack Query 管理。
