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
  const draft = ref("");

  // 发送条件属于跨组件共享的会话状态，集中计算可以避免多个输入入口各自实现校验。
  const canSend = computed(() => draft.value.trim().length > 0);

  function setDraft(content: string) {
    // 快捷问题与输入框共用同一份草稿，避免两个入口出现内容不同步。
    draft.value = content;
  }

  function sendMessage() {
    // 先标准化输入，保证空白消息不会进入状态、更不会在接入后端后产生无效请求。
    const content = draft.value.trim();
    if (!content) return;

    // 目前只完成浏览器内的交互闭环，下一阶段会在这里接入 FastAPI 的 SSE 流式响应。
    messages.value.push({
      id: crypto.randomUUID(),
      role: "customer",
      content,
      time: new Intl.DateTimeFormat("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(new Date()),
    });

    // 只有消息成功写入本地状态后才清空草稿，未来请求失败时可以保留原文供用户重试。
    draft.value = "";
  }

  return { messages, draft, canSend, setDraft, sendMessage };
});
