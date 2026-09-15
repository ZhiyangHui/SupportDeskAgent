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
  // Agent 没有执行建单时两个字段为 null，前端不能依据回复文本猜测副作用是否成功。
  created_ticket_id: z.uuid().nullable(),
  created_ticket_code: z.string().nullable(),
  agent_run_id: z.uuid(),
  // 明确区分只读查询与建单，兼容升级前没有此字段的响应。
  queried_tickets: z.boolean().default(false),
});

export const conversationMessageSchema = z.object({
  id: z.uuid(),
  role: messageRoleSchema,
  content: z.string().min(1),
  created_at: z.iso.datetime({ offset: true }),
  tool_call: z
    .object({
      name: z.enum(["create_support_ticket", "query_support_tickets"]),
      status: z.literal("success"),
      ticket_code: z.string().min(1).nullable(),
    })
    .nullable(),
});

export const conversationMessagesSchema = z.array(conversationMessageSchema);
export type AgentChatResponse = z.infer<typeof agentChatResponseSchema>;
export type ConversationMessage = z.infer<typeof conversationMessageSchema>;
