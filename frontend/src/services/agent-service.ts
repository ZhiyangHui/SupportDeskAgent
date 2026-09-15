import { httpClient } from "@/lib/http";
import {
  agentChatResponseSchema,
  conversationMessagesSchema,
  type AgentChatResponse,
  type ConversationMessage,
} from "@/types/agent";

export interface SendAgentMessageInput {
  clientRequestId: string;
  contextVersion: number;
  companyId: string;
  message: string;
  conversationId: string | null;
}

/** 发送本轮消息；首次不传会话 ID，后续复用后端返回的稳定 ID。 */
export async function sendAgentMessage(input: SendAgentMessageInput): Promise<AgentChatResponse> {
  // 工具循环会产生多次模型请求：为意图判断和最长 90 秒的查询预算预留等待时间。
  // 只延长聊天请求，普通列表接口仍使用统一客户端的短超时。
  const response = await httpClient.post<unknown>("/api/v1/agent/chat", {
    company_id: input.companyId,
    message: input.message,
    conversation_id: input.conversationId,
    client_request_id: input.clientRequestId,
  }, { timeout: 180_000 });
  return agentChatResponseSchema.parse(response.data);
}

/** 加载持久化历史，外部响应进入页面状态前必须通过 Zod 校验。 */
export async function getConversationMessages(
  conversationId: string,
): Promise<ConversationMessage[]> {
  const response = await httpClient.get<unknown>(
    `/api/v1/conversations/${encodeURIComponent(conversationId)}/messages`,
  );
  return conversationMessagesSchema.parse(response.data);
}
