<script setup lang="ts">
// 企业查看关联会话使用受保护的工单接口，绝不改写客户的会话 Store。
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { httpClient } from "@/lib/http";
import { conversationMessagesSchema } from "@/types/agent";

const props = defineProps<{ ticketId: string }>();
const query = useQuery({
  queryKey: computed(() => ["staff-ticket-messages", props.ticketId]),
  queryFn: async () => {
    const response = await httpClient.get<unknown>(`/api/v1/tickets/${encodeURIComponent(props.ticketId)}/messages`);
    return conversationMessagesSchema.parse(response.data);
  },
});
</script>

<template>
  <section class="detail-section">
    <h3>关联客户会话（只读）</h3>
    <p v-if="query.isLoading.value">
      正在读取会话……
    </p>
    <div v-else-if="query.isError.value">
      <el-alert
        title="会话加载失败或登录已过期"
        type="error"
        :closable="false"
      /><el-button @click="query.refetch()">
        重试
      </el-button>
    </div>
    <p v-else-if="!query.data.value?.length">
      暂无关联会话消息
    </p>
    <article
      v-for="message in query.data.value ?? []"
      :key="message.id"
      class="customer-message"
    >
      <small>{{ message.role === 'customer' ? '客户' : '智能客服' }}</small><p>{{ message.content }}</p>
    </article>
  </section>
</template>
