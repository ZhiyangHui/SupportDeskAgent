// 客户接口按登录客户过滤，返回值在边界进行 Zod 校验。
import { z } from "zod";
import { httpClient } from "@/lib/http";
export const companySchema = z.object({ id: z.string().uuid(), name: z.string(), code: z.string() });
export async function getCompany(companyId: string) {
  const response = await httpClient.get<unknown>("/api/v1/customer/companies/" + encodeURIComponent(companyId));
  return companySchema.parse(response.data);
}
export const conversationSchema = z.object({ id: z.string().uuid(), company_id: z.string().uuid(), customer_id: z.string().uuid(), updated_at: z.string() });
const ticketSchema = z.object({ id: z.string().uuid(), code: z.string(), title: z.string(), description: z.string(), status: z.enum(["open", "in_progress", "waiting_customer", "resolved", "closed"]), updated_at: z.string(), company_id: z.string().uuid(), company_name: z.string() });
export async function listMyTickets(page: number) {
  const response = await httpClient.get<unknown>("/api/v1/customer/tickets", { params: { offset: (page - 1) * 20, limit: 20 } });
  return z.object({ items: z.array(ticketSchema), total: z.number() }).parse(response.data);
}
export async function listCompanies(page: number, keyword: string) {
  const response = await httpClient.get<unknown>("/api/v1/customer/companies", { params: { offset: (page - 1) * 20, limit: 20, keyword } });
  return z.array(companySchema).parse(response.data);
}
export async function listMyConversations(companyId: string, page: number) {
  const response = await httpClient.get<unknown>("/api/v1/customer/conversations", { params: { company_id: companyId, offset: (page - 1) * 20, limit: 20 } });
  return z.array(conversationSchema).parse(response.data);
}
