import { z } from "zod";

export const agentRunStatusSchema = z.enum(["running", "succeeded", "failed"]);
export const agentRunSchema = z.object({
  id: z.uuid(),
  request_id: z.string(),
  conversation_id: z.uuid().nullable(),
  ticket_id: z.uuid().nullable(),
  status: agentRunStatusSchema,
  model_name: z.string(),
  intent: z.string().nullable(),
  priority: z.string().nullable(),
  requires_human: z.boolean().nullable(),
  decision_reason: z.string().nullable(),
  tool_name: z.string().nullable(),
  ticket_code: z.string().nullable(),
  duration_ms: z.number().int().nonnegative().nullable(),
  error_type: z.string().nullable(),
  error_message: z.string().nullable(),
  started_at: z.iso.datetime({ offset: true }),
  completed_at: z.iso.datetime({ offset: true }).nullable(),
});
export const agentRunListSchema = z.object({
  items: z.array(agentRunSchema),
  total: z.number().int().nonnegative(),
  offset: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
});
export const agentRunStatisticsSchema = z.object({
  total: z.number().int().nonnegative(),
  running: z.number().int().nonnegative(),
  succeeded: z.number().int().nonnegative(),
  failed: z.number().int().nonnegative(),
  tool_calls: z.number().int().nonnegative(),
  average_duration_ms: z.number().nonnegative(),
});

export type AgentRunStatus = z.infer<typeof agentRunStatusSchema>;
export type AgentRun = z.infer<typeof agentRunSchema>;
export type AgentRunList = z.infer<typeof agentRunListSchema>;
export type AgentRunStatistics = z.infer<typeof agentRunStatisticsSchema>;

export interface AgentRunFilters {
  status: AgentRunStatus | "";
  toolCalled: "" | "true" | "false";
  keyword: string;
  page: number;
  pageSize: number;
}
