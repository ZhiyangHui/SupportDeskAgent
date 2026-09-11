import { z } from "zod";

export const ticketStatusSchema = z.enum([
  "open",
  "in_progress",
  "waiting_customer",
  "resolved",
  "closed",
]);
export const ticketPrioritySchema = z.enum(["low", "medium", "high", "urgent"]);
export const ticketSourceSchema = z.enum(["manual", "agent"]);
export const ticketActivityTypeSchema = z.enum([
  "created",
  "status_changed",
  "priority_changed",
  "assigned",
  "note_added",
]);

export const ticketActivitySchema = z.object({
  id: z.uuid(),
  activity_type: ticketActivityTypeSchema,
  operator_name: z.string(),
  content: z.string().nullable(),
  from_value: z.string().nullable(),
  to_value: z.string().nullable(),
  created_at: z.iso.datetime({ offset: true }),
});

const ticketSummaryFields = {
  id: z.uuid(),
  code: z.string(),
  title: z.string(),
  category: z.string(),
  status: ticketStatusSchema,
  priority: ticketPrioritySchema,
  source: ticketSourceSchema,
  customer_name: z.string().nullable(),
  assignee_name: z.string().nullable(),
  created_at: z.iso.datetime({ offset: true }),
  updated_at: z.iso.datetime({ offset: true }),
};

export const ticketSummarySchema = z.object(ticketSummaryFields);
export const ticketSchema = z.object({
  ...ticketSummaryFields,
  conversation_id: z.uuid().nullable(),
  description: z.string(),
  customer_email: z.string().nullable(),
  version: z.number().int().positive(),
  activities: z.array(ticketActivitySchema),
});
export const ticketListSchema = z.object({
  items: z.array(ticketSummarySchema),
  total: z.number().int().nonnegative(),
  offset: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
});
export const ticketStatisticsSchema = z.object({
  total: z.number().int().nonnegative(),
  open: z.number().int().nonnegative(),
  in_progress: z.number().int().nonnegative(),
  waiting_customer: z.number().int().nonnegative(),
  resolved: z.number().int().nonnegative(),
  closed: z.number().int().nonnegative(),
});

// 新建表单在进入网络层之前完成校验，避免把明显不完整的数据交给后端处理。
// conversation_id 仍由后端再次校验，因为只有数据库才能判断会话是否真实存在。
export const createTicketInputSchema = z.object({
  title: z.string().trim().min(2, "标题至少需要 2 个字").max(200, "标题不能超过 200 个字"),
  description: z
    .string()
    .trim()
    .min(2, "问题描述至少需要 2 个字")
    .max(10000, "问题描述不能超过 10000 个字"),
  category: z.string().trim().min(1, "请选择问题分类").max(50),
  priority: ticketPrioritySchema,
  conversation_id: z.uuid("关联会话 ID 格式不正确").nullable().optional(),
  customer_name: z.string().trim().max(100, "客户姓名不能超过 100 个字").optional(),
  customer_email: z
    .union([z.email("请输入正确的客户邮箱"), z.literal("")])
    .optional(),
  operator_name: z.string().trim().min(1).max(100),
});

export type TicketStatus = z.infer<typeof ticketStatusSchema>;
export type TicketPriority = z.infer<typeof ticketPrioritySchema>;
export type TicketActivityType = z.infer<typeof ticketActivityTypeSchema>;
export type Ticket = z.infer<typeof ticketSchema>;
export type TicketSummary = z.infer<typeof ticketSummarySchema>;
export type TicketList = z.infer<typeof ticketListSchema>;
export type TicketStatistics = z.infer<typeof ticketStatisticsSchema>;

export interface TicketFilters {
  status: TicketStatus | "";
  priority: TicketPriority | "";
  keyword: string;
  page: number;
  pageSize: number;
}

export type CreateTicketInput = z.infer<typeof createTicketInputSchema>;

export interface UpdateTicketInput {
  id: string;
  status?: TicketStatus;
  priority?: TicketPriority;
  assignee_name?: string | null;
  operator_name: string;
}
