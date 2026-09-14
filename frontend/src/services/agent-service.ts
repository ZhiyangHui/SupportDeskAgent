import { httpClient } from "@/lib/http";
import {
  agentChatResponseSchema,
  conversationMessagesSchema,
  type AgentChatResponse,
  type ConversationMessage,
} from "@/types/agent";

export interface SendAgentMessageInput {
  contextVersion: number;
  companyId: string;
  message: string;
  conversationId: string | null;
}

/** 发送本轮消息；首次不传会话 ID，后续复用后端返回的稳定 ID。 */
export async function sendAgentMessage(input: SendAgentMessageInput): Promise<AgentChatResponse> {
  const response = await httpClient.post<unknown>("/api/v1/agent/chat", {
    company_id: input.companyId,
    message: input.message,
    conversation_id: input.conversationId,
  });
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
