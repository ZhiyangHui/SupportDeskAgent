<script setup lang="ts">
// 聊天继续复用原有编排，不将网络状态和业务请求重新写到页面中。
import { computed, ref } from "vue";
import { useRoute } from "vue-router";
import { useQuery } from "@tanstack/vue-query";
import { getCompany, listMyConversations } from "@/services/customer-service";
import { storeToRefs } from "pinia";
import { useAgentChat } from "@/composables/useAgentChat";
import { useChatKeyboard } from "@/composables/useChatKeyboard";
import { useConversationStore } from "@/stores/conversation";

const store = useConversationStore();
const companyId = String(useRoute().params.companyId);
store.selectCompany(companyId);
// 从订单页进入时仅为空草稿预填编号，不能覆盖客户尚未发送的问题。
const selectedOrderCode = useRoute().query.orderCode;
if (!store.draft.trim() && typeof selectedOrderCode === "string" && selectedOrderCode.length <= 40) {
  store.setDraft(`订单 ${selectedOrderCode}，我的问题是：`);
}
const historyPage = ref(1);
const company = useQuery({ queryKey: ["company", companyId], queryFn: () => getCompany(companyId), retry: false });
const history = useQuery({ queryKey: computed(() => ["customer-conversations", companyId, historyPage.value]), queryFn: () => listMyConversations(companyId, historyPage.value) });
const { messages, draft, canSend } = storeToRefs(store);
const { submitDraft, isPending, isLoadingHistory, isHumanMode, isWaitingHuman, error, errorMessage } = useAgentChat();
const busy = computed(() => isPending.value || isLoadingHistory.value || !company.data.value);
const { onChatKeydown } = useChatKeyboard(() => canSend.value && !busy.value, submitDraft);
function restoreConversation(id: string): void {
  store.clearConversation();
  store.setConversationId(id);
}
</script>

<template>
  <main class="portal-panel customer-chat">
    <p v-if="company.isPending.value">
      正在确认企业信息……
    </p>
    <el-alert
      v-if="company.isError.value"
      title="企业不存在、已停用或服务不可用，请返回企业列表重新选择"
      type="error"
      :closable="false"
    />
    <h2>{{ company.data.value?.name }}</h2>
    <header class="portal-section-heading">
      <div><h1>有什么可以帮您？</h1><p>描述遇到的问题，我会协助解答；需要跟进时，可以请我创建工单。</p></div>
      <el-button
        :disabled="busy"
        @click="store.clearConversation()"
      >
        新建会话
      </el-button>
    </header>
    <!-- 历史归属从服务端校验，不再通过浏览器凭证认领数据。 -->
    <el-alert
      v-if="isWaitingHuman"
      title="已提交人工接管请求，正在等待客服接入。您可以继续补充问题。"
      type="warning"
      :closable="false"
    />
    <el-alert
      v-if="isHumanMode"
      title="人工客服已接管，您的消息将直接提交客服，智能客服暂停回复。"
      type="info"
      :closable="false"
    />
    <details>
      <summary>查看与该企业的历史会话</summary>
      <p v-if="history.isPending.value">
        加载中……
      </p><p v-else-if="history.isError.value">
        历史会话加载失败
      </p><p v-else-if="!history.data.value?.length">
        暂无历史会话
      </p>
      <el-button
        v-for="item in history.data.value ?? []"
        :key="item.id"
        :disabled="busy"
        @click="restoreConversation(item.id)"
      >
        {{ new Date(item.updated_at).toLocaleString('zh-CN') }} · {{ item.id.slice(0, 8) }}
      </el-button>
      <div class="portal-actions">
        <el-button
          :disabled="historyPage === 1 || busy"
          @click="historyPage--"
        >
          上一页
        </el-button><el-button
          :disabled="(history.data.value?.length ?? 0) < 20 || busy"
          @click="historyPage++"
        >
          下一页
        </el-button><el-button @click="history.refetch()">
          刷新历史
        </el-button>
      </div>
    </details>
    <!-- 不再展示虚构客户姓名、置信度、客服身份或模型运行节点。 -->
    <div
      class="customer-messages"
      aria-live="polite"
    >
      <!-- 欢迎语是固定能力说明，不写入业务消息或模型记忆，也不触发模型请求。
           保留在对话顶部，发送首条消息后不会消失；恢复历史时不伪造历史消息。 -->
      <article
        v-if="!isLoadingHistory && company.data.value"
        class="customer-message agent"
        aria-label="客服自我介绍"
      >
        <small>智能客服 · 服务介绍</small>
        <p>您好！我是{{ company.data.value.name }}的智能客服，可以帮您：</p>
        <p>一、解答咨询：了解您的问题，提供处理建议。</p>
        <p>二、查询订单：查看您在本企业的模拟订单，确认需要处理的订单。</p>
        <p>三、创建工单：根据您的描述记录问题，或为指定订单创建退款、换货、维修等售后工单；信息不足时，我会向您询问。</p>
        <p>四、跟进工单：选择工单后查看并修改标题、问题描述、售后诉求和影响说明，确认后提交。</p>
        <p>目前订单为模拟数据，创建售后工单不代表已执行退款或换货；企业客服接管后，可由人工继续回复。</p>
      </article>
      <p v-if="isLoadingHistory">
        正在恢复会话……
      </p>
      <article
        v-for="message in messages"
        :key="message.id"
        class="customer-message"
        :class="message.role"
      >
        <small>{{ message.role === 'staff' ? '人工客服' : message.role === 'agent' ? '智能客服' : '我' }} · {{ message.time }}</small>
        <p>{{ message.content }}</p>
        <RouterLink
          v-if="message.toolCall"
          class="portal-action-link"
          :to="message.toolCall.name === 'query_my_orders' ? `/customer/companies/${companyId}/orders` : '/customer/tickets'"
        >
          <!-- 查询标记来自后端真实执行结果，不能把只读查询显示成创建成功。 -->
          {{ message.toolCall.name === "query_support_tickets"
            ? "已查询当前企业的工单，查看我的工单 →"
            : message.toolCall.name === "query_my_orders" ? "已查询您的模拟订单"
              : message.toolCall.name === "append_ticket_comment" ? `已补充到工单 ${message.toolCall.ticketCode}，查看记录 →`
                : message.toolCall.name === "update_support_ticket" ? `工单 ${message.toolCall.ticketCode} 已修改，查看记录 →`
                  : `工单 ${message.toolCall.ticketCode} 已创建，查看进度 →` }}
        </RouterLink>
      </article>
      <p
        v-if="isPending"
        role="status"
      >
        {{ isHumanMode ? '正在提交消息给人工客服……' : '智能客服正在回复，请稍候……' }}
      </p>
    </div>
    <el-alert
      v-if="error"
      :title="errorMessage"
      type="error"
      :closable="false"
    />
    <!-- 申请人工只填入草稿，不承诺已有客服接管，更不在点击时自动产生工单。 -->
    <div class="portal-actions">
      <el-button
        :disabled="busy"
        @click="store.setDraft('请帮我创建一个订单售后工单')"
      >
        创建工单
      </el-button>
      <el-button
        :disabled="busy"
        @click="store.setDraft('我需要人工客服，请记录我的问题并安排跟进')"
      >
        申请人工跟进
      </el-button>
      <!-- 订单与工单入口集中在输入框上方，方便客户咨询时查看相关业务记录。 -->
      <RouterLink
        class="portal-action-link"
        :to="`/customer/companies/${companyId}/orders`"
      >
        我的模拟订单 →
      </RouterLink>
      <RouterLink
        class="portal-action-link"
        to="/customer/tickets"
      >
        查看我的工单
      </RouterLink>
    </div>
    <form @submit.prevent="submitDraft">
      <el-input
        v-model="draft"
        type="textarea"
        :rows="4"
        :maxlength="4000"
        placeholder="请描述您的问题、影响和期望的处理结果"
        :disabled="isLoadingHistory"
        @keydown="onChatKeydown"
      />
      <small>Enter 发送，Shift+Enter 换行。</small>
      <div class="portal-actions">
        <small>人工实时接管尚未开放，您可以通过工单跟进处理状态。</small><el-button
          native-type="submit"
          type="primary"
          :loading="isPending"
          :disabled="!canSend || busy"
        >
          发送
        </el-button>
      </div>
    </form>
  </main>
</template>
