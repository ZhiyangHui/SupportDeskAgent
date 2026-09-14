// 企业客户服务只使用员工认证接口，不能回退到平台客户目录。
import { z } from "zod";
import { httpClient } from "@/lib/http";
import { conversationMessagesSchema } from "@/types/agent";
const customerSchema = z.object({ id: z.string().uuid(), display_name: z.string(), conversation_count: z.number(), updated_at: z.string() });
const conversationSchema = z.object({ id: z.string().uuid(), customer_id: z.string().uuid(), customer_name: z.string(), updated_at: z.string() });
export async function listStaffCustomers(page: number, keyword: string) {
  const response = await httpClient.get<unknown>("/api/v1/staff/customers", { params: { offset: (page - 1) * 20, limit: 20, keyword } });
  return z.array(customerSchema).parse(response.data);
}
export async function listStaffConversations(customerId?: string, page = 1) {
  const response = await httpClient.get<unknown>("/api/v1/staff/conversations", { params: { customer_id: customerId, offset: (page - 1) * 20, limit: 20 } });
  return z.array(conversationSchema).parse(response.data);
}
export async function getStaffMessages(id: string) {
  const response = await httpClient.get<unknown>("/api/v1/staff/conversations/" + encodeURIComponent(id) + "/messages");
  return conversationMessagesSchema.parse(response.data);
}
