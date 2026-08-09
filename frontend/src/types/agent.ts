import { z } from "zod";

// 这些枚举值来自后端 Pydantic 模型。集中定义后，接口字段变化时只需要修改一处。
export const supportIntentSchema = z.enum([
  "general",
  "account",
  "order",
  "ticket",
  "complaint",
]);

export const ticketPrioritySchema = z.enum(["low", "medium", "high", "urgent"]);

// TypeScript 无法约束运行时网络数据，因此响应进入应用前必须经过 Zod 校验。
export const agentChatResponseSchema = z.object({
  reply: z.string().min(1),
  intent: supportIntentSchema,
  priority: ticketPrioritySchema,
  requires_human: z.boolean(),
  reason: z.string().min(1),
});

export type AgentChatResponse = z.infer<typeof agentChatResponseSchema>;