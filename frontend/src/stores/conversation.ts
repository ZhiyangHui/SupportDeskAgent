// 会话 Store 只维护跨组件共享的客户端状态，服务端会话历史将交给 TanStack Query 缓存。
import { defineStore } from "pinia";
import { computed, ref } from "vue";

import type { SupportMessage } from "@/types/support";

// 演示消息暂时保留在前端，接入后端后将由会话查询接口提供初始数据。
const initialMessages: SupportMessage[] = [
  {
    id: "message-1",
    role: "agent",
    content: "您好，我是 SupportDesk 智能客服。请告诉我您遇到的问题，我会优先从企业知识库中查找答案。",
    time: "09:42",
  },
  {
    id: "message-2",
    role: "customer",
    content: "我的企业版账号今天突然无法登录，重置密码后仍然提示账号异常。",
    time: "09:43",
  },
  {
    id: "message-3",
    role: "agent",
    content: "我已识别到这是账号访问问题。为保护企业数据，我会先核对账号状态；如果检测到安全风险，将自动转交人工客服处理。",
    time: "09:43",
  },
];

export const useConversationStore = defineStore("conversation", () => {
  // messages 会同时被消息列表和未来的会话摘要消费，因此放入 Pinia，而不是页面局部状态。
  const messages = ref<SupportMessage[]>(initialMessages);
  const draft=ref("");

  // 发送条件集中计算，快捷问题和文本输入就不会分别维护一套校验规则。
  const canSend = computed(() => draft.value.trim().length > 0);

  function setDraft(content: string): void {
    // 快捷问题与输入框共用同一份草稿，避免两个入口出现内容不同步。
    draft.value = content;
  }

  function takeDraft(): string | null {
    // 返回标准化后的快照，避免请求期间输入框变化影响已经发出的消息。
    const content = draft.value.trim();
    if (!content) return null;

    draft.value = "";
    return content;
  }

  function restoreDraft(content: string): void {
    // 用户可能已开始输入下一条消息，因此失败恢复不能覆盖非空草稿。
    if (!draft.value.trim()) draft.value = content;
  }

  function appendMessage(role: SupportMessage["role"], content: string): void {
    const normalizedContent = content.trim();
    if (!normalizedContent) return;

    messages.value.push({
      id: crypto.randomUUID(),
      role,
      content: normalizedContent,
      time: new Intl.DateTimeFormat("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(new Date()),
    });
  }

  function appendCustomerMessage(content: string): void {
    appendMessage("customer", content);
  }

  function appendAgentMessage(content: string): void {
    appendMessage("agent", content);
  }

  return {
    messages,
    draft,
    canSend,
    setDraft,
    takeDraft,
    restoreDraft,
    appendCustomerMessage,
    appendAgentMessage,
  };

});
