import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, watchEffect } from "vue";

import {
  getConversationMessages,
  sendAgentMessage,
  type SendAgentMessageInput,
} from "@/services/agent-service";
import { useConversationStore } from "@/stores/conversation";

/** 连接持久化历史、聊天请求和会话 UI 状态。 */
export function useAgentChat() {
  const conversationStore = useConversationStore();
  const queryClient = useQueryClient();
  const historyQuery = useQuery({
    queryKey: computed(() => ["conversation-messages", conversationStore.conversationId]),
    queryFn: () => getConversationMessages(conversationStore.conversationId as string),
    enabled: computed(() => conversationStore.conversationId !== null),
    retry: false,
  });

  // 查询成功后以数据库历史为准，页面刷新时不会继续展示本地演示消息。
  watchEffect(() => {
    if (historyQuery.data.value) conversationStore.replaceWithHistory(historyQuery.data.value);
  });

  const mutation = useMutation({
    mutationFn: sendAgentMessage,
    async onSuccess(response) {
      conversationStore.setConversationId(response.conversation_id);
      conversationStore.appendAgentMessage(
        response.reply,
        response.agent_message_id,
        response.created_ticket_code
          ? {
              name: "create_support_ticket",
              status: "success",
              ticketCode: response.created_ticket_code,
            }
          : undefined,
      );
      if (response.created_ticket_id) {
        // Agent 建单后主动让所有工单摘要失效，聊天侧栏和工单中心会自动读取最新数据。
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["tickets"] }),
          queryClient.invalidateQueries({ queryKey: ["ticket-statistics"] }),
        ]);
      }
    },
    onError(_error, variables) {
      conversationStore.restoreDraft(variables.message);
    },
  });

  function submitDraft(): void {
    // 历史恢复和模型调用期间都不发送新消息，避免异步结果覆盖刚写入的本地状态。
    if (mutation.isPending.value || historyQuery.isFetching.value) return;
    const content = conversationStore.takeDraft();
    if (!content) return;

    conversationStore.appendCustomerMessage(content);
    const input: SendAgentMessageInput = {
      message: content,
      conversationId: conversationStore.conversationId,
    };
    mutation.mutate(input);
  }

  return {
    submitDraft,
    isPending: mutation.isPending,
    // isFetching 只在真正发起历史请求时为 true，首次会话不会误显示加载状态。
    isLoadingHistory: historyQuery.isFetching,
    error: computed(() => mutation.error.value ?? historyQuery.error.value),
  };
}
