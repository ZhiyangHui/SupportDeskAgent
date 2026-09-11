// 会话 Store 只维护浏览器端共享状态；历史数据的请求生命周期交给 TanStack Query。
import { defineStore } from "pinia";
import { computed, ref } from "vue";

import type { ConversationMessage } from "@/types/agent";
import type { MessageRole, SupportMessage } from "@/types/support";

const CONVERSATION_ID_KEY = "supportdesk.conversation-id";

function formatMessageTime(value: Date | string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export const useConversationStore = defineStore("conversation", () => {
  const messages = ref<SupportMessage[]>([]);
  const draft = ref("");
  // localStorage 只保存无敏感信息的会话 ID，刷新页面后可据此恢复服务端历史。
  const conversationId = ref<string | null>(localStorage.getItem(CONVERSATION_ID_KEY));
  const canSend = computed(() => draft.value.trim().length > 0);

  function setConversationId(value: string): void {
    conversationId.value = value;
    localStorage.setItem(CONVERSATION_ID_KEY, value);
  }

  function setDraft(content: string): void {
    draft.value = content;
  }

  function takeDraft(): string | null {
    const content = draft.value.trim();
    if (!content) return null;
    draft.value = "";
    return content;
  }

  function restoreDraft(content: string): void {
    // 请求失败时只恢复到空输入框，避免覆盖用户等待期间输入的新问题。
    if (!draft.value.trim()) draft.value = content;
  }

  function appendMessage(
    role: MessageRole,
    content: string,
    // 显式声明为 string，避免默认 UUID 值把参数推导成过窄的模板字符串类型。
    id: string = crypto.randomUUID(),
    toolCall?: SupportMessage["toolCall"],
  ): void {
    const normalizedContent = content.trim();
    if (!normalizedContent) return;
    messages.value.push({
      id,
      role,
      content: normalizedContent,
      time: formatMessageTime(new Date()),
      toolCall,
    });
  }

  function appendCustomerMessage(content: string, id?: string): void {
    appendMessage("customer", content, id);
  }

  function appendAgentMessage(
    content: string,
    id?: string,
    toolCall?: SupportMessage["toolCall"],
  ): void {
    appendMessage("agent", content, id, toolCall);
  }

  function replaceWithHistory(history: ConversationMessage[]): void {
    // 数据库是历史消息的事实来源，初始化时整体替换，避免演示数据与真实记录混合。
    messages.value = history.map((message) => ({
      id: message.id,
      role: message.role,
      content: message.content,
      time: formatMessageTime(message.created_at),
      toolCall: message.tool_call
        ? {
            name: message.tool_call.name,
            status: message.tool_call.status,
            ticketCode: message.tool_call.ticket_code,
          }
        : undefined,
    }));
  }

  function clearConversation(): void {
    conversationId.value = null;
    messages.value = [];
    localStorage.removeItem(CONVERSATION_ID_KEY);
  }

  return {
    messages,
    draft,
    conversationId,
    canSend,
    setConversationId,
    setDraft,
    takeDraft,
    restoreDraft,
    appendCustomerMessage,
    appendAgentMessage,
    replaceWithHistory,
    clearConversation,
  };
});
