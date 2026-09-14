// 双端使用独立 API 与 Cookie，账号信息属于服务端状态，不保存密码或令牌。
import { z } from "zod";
import { httpClient } from "@/lib/http";
import { notifyAuthChange } from "@/lib/auth-events";
export type Audience = "customer" | "staff";
export const principalSchema = z.object({
  id: z.string().uuid(), audience: z.enum(["customer", "staff"]), display_name: z.string(),
  company_id: z.string().uuid().nullable(), company_name: z.string().nullable(),
});
export type Principal = z.infer<typeof principalSchema>;
export const accountInputSchema = z.object({
  username: z.string().trim().min(3).max(64).regex(/^[a-zA-Z0-9_.-]+$/),
  // 登录兼容已有账号的密码；注册长度由独立规则约束，不修改实际密码内容。
  password: z.string().min(1).max(128),
});
// 按 Unicode 字符计数，与后端一致，避免表情符号在两端得到不同长度。
export const registrationPasswordSchema = z.string().refine(
  (value) => [...value].length >= 8 && [...value].length <= 20,
  "注册密码需要 8～20 个字符，无字符种类要求",
);
export async function getIdentity(audience: Audience): Promise<Principal> {
  const response = await httpClient.get<unknown>("/api/v1/access/" + audience);
  return principalSchema.parse(response.data);
}
export const checkStaffSession = () => getIdentity("staff");
export const initializeCustomer = () => getIdentity("customer");
export async function loginAccount(audience: Audience, input: { username: string; password: string; company_code?: string }): Promise<Principal> {
  const response = await httpClient.post<unknown>("/api/v1/access/" + audience + "/login", input);
  return principalSchema.parse(response.data);
}
export async function registerAccount(audience: Audience, input: { username: string; password: string; display_name: string; company_code?: string; company_name?: string }): Promise<void> {
  await httpClient.post(audience === "customer" ? "/api/v1/access/customer/register" : "/api/v1/access/staff/register-company", input);
}
export async function logoutAccount(audience: Audience): Promise<void> {
  await httpClient.post("/api/v1/access/" + audience + "/logout");
  notifyAuthChange(audience);
}
export const logoutStaff = () => logoutAccount("staff");
