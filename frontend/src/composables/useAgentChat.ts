import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, watchEffect } from "vue";

import {
  getConversationMessages,
  sendAgentMessage,
  type SendAgentMessageInput,
} from "@/services/agent-service";
import { useConversationStore } from "@/stores/conversation";
import { agentErrorDetail, agentErrorMessage } from "@/services/agent-feedback";

/** 连接持久化历史、聊天请求和会话 UI 状态。 */
export function useAgentChat() {
  const conversationStore = useConversationStore();
  const queryClient = useQueryClient();
  // 保留失败请求的键与原始会话参数；未知结果重试时不能被当作一次新的建单。
  let pendingInput: SendAgentMessageInput | null = null;
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
    retry: false,
    async onSuccess(response, variables) {
      // 切换企业后，旧请求仍可能在服务器完成，但不得把回复写进新企业会话。
      if (conversationStore.companyId !== variables.companyId || conversationStore.contextVersion !== variables.contextVersion) return;
      pendingInput = null;
      conversationStore.setConversationId(response.conversation_id);
      void queryClient.invalidateQueries({ queryKey: ["customer-conversations"] });
      conversationStore.appendAgentMessage(
        response.reply,
        response.agent_message_id,
        response.created_ticket_code
          ? {
              name: "create_support_ticket",
              status: "success",
              ticketCode: response.created_ticket_code,
            }
          : response.queried_tickets
            ? { name: "query_support_tickets", status: "success", ticketCode: null }
            : undefined,
      );
      if (response.created_ticket_id) {
        // Agent 建单后主动让所有工单摘要失效，聊天侧栏和工单中心会自动读取最新数据。
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["tickets"] }),
          queryClient.invalidateQueries({ queryKey: ["customer-tickets"] }),
          queryClient.invalidateQueries({ queryKey: ["ticket-statistics"] }),
        ]);
      }
    },
    onError(_error, variables) {
      if (conversationStore.companyId !== variables.companyId || conversationStore.contextVersion !== variables.contextVersion) return;
      const detail = agentErrorDetail(_error);
      if (detail?.outcome === "ticket_created") {
        // 操作已成功时不把建单内容放回输入框，提醒客户从工单中心核对。
        pendingInput = variables;
        void queryClient.invalidateQueries({ queryKey: ["customer-tickets"] });
      } else {
        conversationStore.restoreDraft(variables.message);
        // 只有后端明确证明没有开始写入，才允许用户手动发起一个新尝试。
        if (detail?.outcome === "not_executed" && detail.retryable) pendingInput = null;
      }
    },
  });

  function submitDraft(): void {
    // 历史恢复和模型调用期间都不发送新消息，避免异步结果覆盖刚写入的本地状态。
    if (mutation.isPending.value || historyQuery.isFetching.value || !conversationStore.companyId) return;
    const content = conversationStore.takeDraft();
    if (!content) return;

    conversationStore.appendCustomerMessage(content);
    const input: SendAgentMessageInput = {
      clientRequestId: crypto.randomUUID(),
      contextVersion: conversationStore.contextVersion,
      companyId: conversationStore.companyId,
      message: content,
      conversationId: conversationStore.conversationId,
    };
    const sameAttempt = pendingInput?.companyId === input.companyId &&
      pendingInput.contextVersion === input.contextVersion && pendingInput.message === input.message;
    pendingInput = sameAttempt ? pendingInput : input;
    mutation.mutate(pendingInput ?? input);
  }

  return {
    submitDraft,
    isPending: mutation.isPending,
    // isFetching 只在真正发起历史请求时为 true，首次会话不会误显示加载状态。
    isLoadingHistory: historyQuery.isFetching,
    error: computed(() => mutation.error.value ?? historyQuery.error.value),
    errorMessage: computed(() => agentErrorMessage(mutation.error.value ?? historyQuery.error.value)),
  };
}
