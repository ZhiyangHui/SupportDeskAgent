import { httpClient } from "@/lib/http";
import {
  ticketListSchema,
  ticketSchema,
  ticketStatisticsSchema,
  type CreateTicketInput,
  type Ticket,
  type TicketFilters,
  type TicketList,
  type TicketStatistics,
  type UpdateTicketInput,
} from "@/types/ticket";

/** 查询工单列表，空筛选项不发送，保持 URL 简洁且避免后端枚举校验失败。 */
export async function listTickets(filters: TicketFilters): Promise<TicketList> {
  const response = await httpClient.get<unknown>("/api/v1/tickets", {
    params: {
      customer_id: filters.customerId,
      status: filters.status || undefined,
      priority: filters.priority || undefined,
      keyword: filters.keyword.trim() || undefined,
      offset: (filters.page - 1) * filters.pageSize,
      limit: filters.pageSize,
    },
  });
  return ticketListSchema.parse(response.data);
}

export async function getTicket(ticketId: string): Promise<Ticket> {
  const response = await httpClient.get<unknown>(`/api/v1/tickets/${encodeURIComponent(ticketId)}`);
  return ticketSchema.parse(response.data);
}

export async function getTicketStatistics(): Promise<TicketStatistics> {
  const response = await httpClient.get<unknown>("/api/v1/tickets/statistics");
  return ticketStatisticsSchema.parse(response.data);
}

export async function createTicket(input: CreateTicketInput): Promise<Ticket> {
  // 表单使用空字符串便于双向绑定，但后端可选字段的语义是 null/缺省。
  // 在 HTTP 边界统一清理空值，避免选填邮箱因 "" 无法通过 EmailStr 校验而返回 422。
  const payload = {
    ...input,
    customer_name: input.customer_name?.trim() || undefined,
    customer_email: input.customer_email?.trim() || undefined,
  };
  const response = await httpClient.post<unknown>("/api/v1/tickets", payload);
  return ticketSchema.parse(response.data);
}

export async function updateTicket(input: UpdateTicketInput): Promise<Ticket> {
  const { id, ...payload } = input;
  const response = await httpClient.patch<unknown>(
    `/api/v1/tickets/${encodeURIComponent(id)}`,
    payload,
  );
  return ticketSchema.parse(response.data);
}

export async function addTicketNote(input: {
  id: string;
  content: string;
  operator_name: string;
}): Promise<Ticket> {
  const response = await httpClient.post<unknown>(
    `/api/v1/tickets/${encodeURIComponent(input.id)}/notes`,
    { content: input.content, operator_name: input.operator_name },
  );
  return ticketSchema.parse(response.data);
}
