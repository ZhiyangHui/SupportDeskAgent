import { z } from "zod";
import { httpClient } from "@/lib/http";

// 模式始终以服务端为准，前端禁用按钮不能代替接管权限校验。
const stateSchema = z.object({
  status: z.enum(["active", "handed_off", "closed"]),
  handoff_staff_id: z.string().uuid().nullable(),
  handoff_requested_at: z.string().nullable().default(null),
  handoff_reason: z.string().default(""),
});
export async function getHandoff(id: string, audience: "customer" | "staff") {
  return stateSchema.parse((await httpClient.get(`/api/v1/${audience}/conversations/${id}/handoff`)).data);
}
export async function changeHandoff(id: string, action: "takeover" | "resume") {
  return stateSchema.parse((await httpClient.post(`/api/v1/staff/conversations/${id}/handoff`, { action })).data);
}
export async function sendStaffReply(id: string, content: string, key: string) {
  await httpClient.post(`/api/v1/staff/conversations/${id}/reply`, { content, client_request_id: key });
}

const queueSchema = z.object({
  total: z.number().int().nonnegative(),
  items: z.array(z.object({ conversation_id: z.string().uuid(), customer_name: z.string(),
    requested_at: z.string().nullable(), reason: z.string(), status: z.string() })),
});
export async function listHandoffs(scope: "pending" | "mine", page = 1) {
  return queueSchema.parse((await httpClient.get("/api/v1/staff/handoffs", {
    params: { scope, offset: (page - 1) * 20, limit: 20 },
  })).data);
}
