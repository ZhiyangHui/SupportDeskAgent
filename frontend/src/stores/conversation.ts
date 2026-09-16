// 会话 Store 只维护浏览器端共享状态；历史数据的请求生命周期交给 TanStack Query。
import { defineStore } from "pinia";
import { computed, ref } from "vue";

import type { ConversationMessage } from "@/types/agent";
import type { MessageRole, SupportMessage } from "@/types/support";

// 新入口不自动复用迁移前没有归属的会话 ID，旧数据仍保留在企业端。
const CONVERSATION_ID_KEY = "supportdesk.customer-conversation-id";

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
  // 不自动认领旧浏览器会话；登录后从服务端按客户与企业恢复历史。
  const conversationId = ref<string | null>(null);
  const companyId = ref<string | null>(null);
  const contextVersion = ref(0);
  // 草稿仅保留在当前浏览器运行期间，不把客户输入写入磁盘；不同企业分别保存。
  const companyDrafts = new Map<string, string>();
  let customerId: string | null = null;

  function resetCustomerState(): void {
    clearConversation();
    companyDrafts.clear();
    draft.value = "";
    companyId.value = null;
    customerId = null;
  }

  function selectCustomer(value: string): void {
    // 身份由服务端确认；重新登录为另一客户时，不能继承上一客户的草稿。
    if (customerId === value) return;
    resetCustomerState();
    customerId = value;
  }

  function selectCompany(value: string): void {
    // 路由离开后组件会重建，但相同企业的会话与未发送输入不应跟着重置。
    if (companyId.value === value) return;
    if (companyId.value) companyDrafts.set(companyId.value, draft.value);
    clearConversation();
    draft.value = companyDrafts.get(value) ?? "";
    companyId.value = value;
  }
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
    contextVersion.value++;
    conversationId.value = null;
    messages.value = [];
    localStorage.removeItem(CONVERSATION_ID_KEY);
  }

  return {
    resetCustomerState,
    selectCustomer,
    contextVersion,
    companyId,
    selectCompany,
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
