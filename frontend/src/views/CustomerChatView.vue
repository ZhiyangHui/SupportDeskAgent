<script setup lang="ts">
// 聊天继续复用原有编排，不将网络状态和业务请求重新写到页面中。
import { computed, ref } from "vue";
import { useRoute } from "vue-router";
import { useQuery } from "@tanstack/vue-query";
import { getCompany, listMyConversations } from "@/services/customer-service";
import { storeToRefs } from "pinia";
import { useAgentChat } from "@/composables/useAgentChat";
import { useConversationStore } from "@/stores/conversation";

const store = useConversationStore();
const companyId = String(useRoute().params.companyId);
store.selectCompany(companyId);
const historyPage = ref(1);
const company = useQuery({ queryKey: ["company", companyId], queryFn: () => getCompany(companyId), retry: false });
const history = useQuery({ queryKey: computed(() => ["customer-conversations", companyId, historyPage.value]), queryFn: () => listMyConversations(companyId, historyPage.value) });
const { messages, draft, canSend } = storeToRefs(store);
const { submitDraft, isPending, isLoadingHistory, error } = useAgentChat();
const busy = computed(() => isPending.value || isLoadingHistory.value || !company.data.value);
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
      <el-empty
        v-if="!messages.length && !isLoadingHistory"
        description="发送第一条消息，开始咨询"
      />
      <p v-if="isLoadingHistory">
        正在恢复会话……
      </p>
      <article
        v-for="message in messages"
        :key="message.id"
        class="customer-message"
        :class="message.role"
      >
        <small>{{ message.role === 'agent' ? '智能客服' : '我' }} · {{ message.time }}</small>
        <p>{{ message.content }}</p>
        <RouterLink
          v-if="message.toolCall"
          to="/customer/tickets"
        >
          工单 {{ message.toolCall.ticketCode }} 已创建，查看进度 →
        </RouterLink>
      </article>
      <p
        v-if="isPending"
        role="status"
      >
        智能客服正在回复，请稍候……
      </p>
    </div>
    <el-alert
      v-if="error"
      title="请求未完成，请检查服务后重试。若旧会话无法恢复，可以新建会话；原数据不会被删除。"
      type="error"
      :closable="false"
    />
    <!-- 申请人工只填入草稿，不承诺已有客服接管，更不在点击时自动产生工单。 -->
    <div class="portal-actions">
      <el-button
        :disabled="busy"
        @click="store.setDraft('请帮我创建一个工单')"
      >
        创建工单
      </el-button>
      <el-button
        :disabled="busy"
        @click="store.setDraft('我需要人工客服，请记录我的问题并安排跟进')"
      >
        申请人工跟进
      </el-button>
      <RouterLink to="/customer/tickets">
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
      />
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
