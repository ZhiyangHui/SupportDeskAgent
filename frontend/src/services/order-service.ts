// 模拟订单边界协议：金额由后端 Decimal 序列化为字符串，不涉及真实支付。
import { z } from "zod";
import { httpClient } from "@/lib/http";
export const orderFormSchema = z.object({
  product_name: z.string().trim().min(1, "请填写商品名称").max(100),
  amount: z.number().positive("金额必须大于零").max(99999999).multipleOf(0.01),
  status: z.enum(["paid", "shipped", "completed"]),
});
const orderSchema = z.object({ id: z.uuid(), code: z.string(), product_name: z.string(), amount: z.string(), status: z.enum(["paid", "shipped", "completed"]), created_at: z.string() });
export type OrderForm = z.infer<typeof orderFormSchema>;
export async function listOrders(companyId: string, page: number) {
  const response = await httpClient.get<unknown>(`/api/v1/customer/companies/${companyId}/orders`, { params: { offset: (page - 1) * 20, limit: 20 } });
  return z.object({ items: z.array(orderSchema), total: z.number() }).parse(response.data);
}
export async function createOrder(companyId: string, data: OrderForm, requestId: string) {
  const response = await httpClient.post<unknown>(`/api/v1/customer/companies/${companyId}/orders`, { ...orderFormSchema.parse(data), client_request_id: requestId });
  return orderSchema.parse(response.data);
}
