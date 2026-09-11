import { z } from "zod";

export const supportIntentSchema = z.enum(["general", "account", "order", "ticket", "complaint"]);
export const ticketPrioritySchema = z.enum(["low", "medium", "high", "urgent"]);
export const messageRoleSchema = z.enum(["customer", "agent"]);

// 前端在运行时校验后端响应，字段名必须与 FastAPI ChatResponse 完全一致。
export const agentChatResponseSchema = z.object({
  conversation_id: z.uuid(),
  customer_message_id: z.uuid(),
  agent_message_id: z.uuid(),
  reply: z.string().min(1),
  intent: supportIntentSchema,
  priority: ticketPrioritySchema,
  requires_human: z.boolean(),
  reason: z.string().min(1),
});

export const conversationMessageSchema = z.object({
  id: z.uuid(),
  role: messageRoleSchema,
  content: z.string().min(1),
  created_at: z.iso.datetime({ offset: true }),
});

export const conversationMessagesSchema = z.array(conversationMessageSchema);
export type AgentChatResponse = z.infer<typeof agentChatResponseSchema>;
export type ConversationMessage = z.infer<typeof conversationMessageSchema>;
