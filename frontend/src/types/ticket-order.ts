import { z } from "zod";

// 客户页与企业页共享只读协议，订单归属和关联关系只能由服务端确定。
export const ticketOrderSchema = z.object({
  code: z.string(),
  product_name: z.string(),
}).nullable().default(null);
