<script setup lang="ts">
import { storeToRefs } from "pinia";
import { useQuery } from "@tanstack/vue-query";
import {
  Bot,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Headphones,
  MessageSquareText,
  Paperclip,
  Search,
  Send,
  Sparkles,
  TicketCheck,
  UserRound,
} from "@lucide/vue";

import { computed } from "vue";
import { useRouter } from "vue-router";
import { useAgentChat } from "@/composables/useAgentChat";
import { listTickets } from "@/services/ticket-service";
import { useConversationStore } from "@/stores/conversation";

// storeToRefs 保留 Pinia 状态的响应性；业务动作仍从 Store 实例调用，职责更加清晰。
const conversationStore = useConversationStore();
const { messages, draft, conversationId, canSend } = storeToRefs(conversationStore);
const { submitDraft, isPending, isLoadingHistory, error, errorMessage } = useAgentChat();
const router = useRouter();
// 历史恢复期间暂停发送，避免查询结果覆盖刚追加的本地临时消息。
const canSubmit = computed(
  () => canSend.value && !isPending.value && !isLoadingHistory.value,
);

const quickQuestions = ["查询工单进度", "账号登录异常", "申请人工客服"];

// 侧栏只加载最近两条摘要，不重复维护一份演示数据；完整筛选和详情仍在工单中心完成。
const recentTicketsQuery = useQuery({
  queryKey: ["tickets", "recent"],
  queryFn: () =>
    listTickets({ status: "", priority: "", keyword: "", page: 1, pageSize: 2 }),
});
const recentTickets = computed(() => recentTicketsQuery.data.value?.items ?? []);

function openTicketCenter(createTicket = false, ticketId?: string): void {
  const query: Record<string, string> = {};
  if (createTicket) {
    query.create = "1";
    // 只有已经落库的会话才能建立外键关联，新会话尚无 ID 时仍允许普通建单。
    if (conversationId.value) query.conversation_id = conversationId.value;
  }
  if (ticketId) query.ticket_id = ticketId;
  void router.push({ name: "ticket-center", query });
}
</script>

<template>
  <main class="app-shell">
    <!-- 左侧导航只负责工作台模块切换，服务状态放在底部以便客服随时确认 Agent 是否可用。 -->
    <aside
      class="sidebar"
      aria-label="工作台导航"
    >
      <div class="brand">
        <div class="brand-mark">
          <Headphones :size="21" />
        </div>
        <div><strong>SupportDesk</strong><span>智能客服工作台</span></div>
      </div>

      <nav class="nav-list">
        <RouterLink
          class="nav-item active"
          to="/"
        >
          <MessageSquareText :size="18" />客户会话<span class="nav-badge">3</span>
        </RouterLink>
        <RouterLink
          class="nav-item"
          to="/tickets"
        >
          <TicketCheck :size="18" />工单中心
        </RouterLink>
        <RouterLink
          class="nav-item"
          to="/agent-runs"
        >
          <Bot :size="18" />Agent 运行记录
        </RouterLink>
      </nav>

      <div class="sidebar-status">
        <span class="status-dot" />
        <div><strong>Agent 服务正常</strong><span>平均响应 1.8 秒</span></div>
      </div>
    </aside>

    <section class="workspace">
      <!-- 顶部区域保留全局搜索和当前账号入口，不与具体会话状态耦合。 -->
      <header class="topbar">
        <div>
          <p class="eyebrow">
            客户支持中心
          </p><h1>上午好，客服专员</h1>
        </div>
        <label class="search-box">
          <Search :size="17" />
          <input
            aria-label="搜索会话或工单"
            placeholder="搜索会话或工单"
          >
        </label>
        <button
          class="profile-button"
          type="button"
          aria-label="打开个人菜单"
        >
          <span>杨</span><div><strong>杨慧之</strong><small>管理员</small></div>
        </button>
      </header>

      <!-- 主工作区保持“会话 + 上下文详情”布局，便于客服在同一屏完成判断和操作。 -->
      <div class="content-grid">
        <section class="conversation-card">
          <!-- 会话头部展示当前客户和 Agent 运行状态，后续状态将来自会话详情接口。 -->
          <div class="conversation-header">
            <div class="customer-avatar">
              <UserRound :size="21" />
            </div>
            <div class="customer-title">
              <div>
                <h2>陈先生</h2><el-tag
                  size="small"
                  type="success"
                  effect="light"
                >
                  在线
                </el-tag>
              </div>
              <p>企业版客户 · 会话 #CS-98231</p>
            </div>
            <div class="agent-chip">
              <Sparkles :size="15" />Agent 正在处理
            </div>
          </div>

          <!-- 这里呈现 LangGraph 已提取的结构化上下文，帮助人工客服快速判断处理进度。 -->
          <div class="context-strip">
            <div><span>意图识别</span><strong>账号访问异常</strong></div>
            <div><span>紧急程度</span><strong class="danger-text">高</strong></div>
            <div><span>当前节点</span><strong>安全状态核验</strong></div>
            <div><span>置信度</span><strong>94%</strong></div>
          </div>

          <!-- aria-live 让新增消息能被辅助技术感知，但不会打断用户当前操作。 -->
          <div
            class="message-list"
            aria-live="polite"
          >
            <div class="timeline-label">
              今天
            </div>
            <!-- 历史加载属于服务端状态，页面只负责提供明确而不遮挡内容的反馈。 -->
            <div
              v-if="isLoadingHistory"
              class="history-loading"
            >
              正在恢复历史会话……
            </div>
            <article
              v-for="message in messages"
              :key="message.id"
              class="message-row"
              :class="message.role"
            >
              <div class="message-avatar">
                <Bot
                  v-if="message.role === 'agent'"
                  :size="17"
                />
                <UserRound
                  v-else
                  :size="17"
                />
              </div>
              <div>
                <div class="message-meta">
                  <strong>{{ message.role === "agent" ? "SupportDesk Agent" : "陈先生" }}</strong>
                  <time>{{ message.time }}</time>
                </div>
                <p class="message-bubble">
                  {{ message.content }}
                </p>
                <div
                  v-if="message.toolCall"
                  class="tool-call"
                >
                  <CheckCircle2 :size="15" />已调用 {{ message.toolCall.name }} ·
                  {{ message.toolCall.ticketCode }}
                </div>
              </div>
            </article>
          </div>

          <!-- 快捷问题只更新草稿，不直接发送，避免用户误触后产生不可撤销的业务请求。 -->
          <div class="quick-actions">
            <el-button
              v-for="question in quickQuestions"
              :key="question"
              round
              size="small"
              @click="conversationStore.setDraft(question)"
            >
              {{ question }}
            </el-button>
          </div>

          <!-- 页面只展示统一错误提示，底层异常仍保留在开发者工具中，避免暴露内部服务信息。 -->
          <el-alert
            v-if="error"
            class="chat-error"
            :title="errorMessage"
            type="error"
            :closable="false"
            show-icon
          />

          <!-- 表单只触发 Composable，网络生命周期与本地会话状态分别由 Query 和 Pinia 维护。 -->
          <form
            class="composer"
            @submit.prevent="submitDraft"
          >
            <textarea
              v-model="draft"
              aria-label="输入消息"
              rows="2"
              placeholder="输入您的问题，按发送继续会话……"
            />
            <div class="composer-toolbar">
              <button
                class="icon-button"
                type="button"
                aria-label="添加附件"
              >
                <Paperclip :size="18" />
              </button>
              <span>Agent 回复会经过安全检查</span>
              <el-button
                native-type="submit"
                type="primary"
                :disabled="!canSubmit"
                :loading="isPending"
              >
                发送<Send :size="15" />
              </el-button>
            </div>
          </form>
        </section>

        <!-- 客户资料和 Agent 执行摘要属于辅助上下文，不与会话消息混入同一个状态模型。 -->
        <aside
          class="details-panel"
          aria-label="客户与工单信息"
        >
          <!-- 客户档案只展示本次处理所需的高频字段，完整资料通过详情入口按需加载。 -->
          <section class="info-card customer-card">
            <div class="card-heading">
              <div>
                <p class="eyebrow">
                  客户档案
                </p><h3>陈先生</h3>
              </div><el-button
                link
                type="primary"
              >
                查看详情
              </el-button>
            </div>
            <dl>
              <div><dt>客户等级</dt><dd>企业专业版</dd></div>
              <div><dt>所属公司</dt><dd>远见数字科技</dd></div>
              <div><dt>服务有效期</dt><dd>2027-03-18</dd></div>
              <div><dt>历史会话</dt><dd>12 次</dd></div>
            </dl>
          </section>

          <!-- 工单列表使用摘要模型，避免为了侧栏展示提前加载完整工单及操作历史。 -->
          <section class="info-card">
            <div class="card-heading">
              <div>
                <p class="eyebrow">
                  关联工单
                </p><h3>最近记录</h3>
              </div><el-button
                link
                type="primary"
                @click="openTicketCenter(true)"
              >
                新建工单
              </el-button>
            </div>
            <div
              v-loading="recentTicketsQuery.isFetching.value"
              class="ticket-list"
            >
              <button
                v-for="ticket in recentTickets"
                :key="ticket.id"
                class="ticket-item"
                type="button"
                @click="openTicketCenter(false, ticket.id)"
              >
                <div
                  class="priority-mark"
                  :class="ticket.priority"
                />
                <div><strong>{{ ticket.title }}</strong><span>{{ ticket.code }} · {{ ticket.status }}</span></div>
                <ChevronRight :size="17" />
              </button>
              <p
                v-if="!recentTicketsQuery.isFetching.value && recentTickets.length === 0"
                class="empty-ticket-hint"
              >
                暂无工单，可从当前会话创建
              </p>
            </div>
          </section>

          <!-- Agent 摘要用于解释当前工作流已完成和等待中的节点，也是人工接管的决策依据。 -->
          <section class="info-card agent-card">
            <div class="agent-card-title">
              <div><Sparkles :size="18" /></div><span><strong>Agent 处理摘要</strong><small>由 LangGraph 工作流生成</small></span>
            </div>
            <ul>
              <li><CheckCircle2 :size="15" />已完成意图与情绪识别</li>
              <li><CheckCircle2 :size="15" />已检索账号安全知识库</li>
              <li class="pending">
                <Clock3 :size="15" />等待账号状态工具返回
              </li>
            </ul>
            <el-button
              class="handoff-button"
              type="warning"
            >
              转交人工客服
            </el-button>
          </section>
        </aside>
      </div>
    </section>
  </main>
</template>
