// 错误在边界处校验，只展示约定的安全字段，不回显原始异常对象。
import axios from "axios";
import { z } from "zod";

const detailSchema = z.object({
  code: z.string(), message: z.string(), request_id: z.string(), retryable: z.boolean(),
  outcome: z.enum(["not_executed", "ticket_created", "unknown"]), ticket_code: z.string().nullable(),
});

export function agentErrorDetail(error: unknown) {
  if (!axios.isAxiosError(error)) return null;
  const parsed = z.object({ detail: detailSchema }).safeParse(error.response?.data);
  return parsed.success ? parsed.data.detail : null;
}

/** 网络中断并不证明服务端没有执行，默认提示核对结果而不是盲目重试。 */
export function agentErrorMessage(error: unknown): string {
  const detail = agentErrorDetail(error);
  if (detail) return `${detail.message}（请求 ID：${detail.request_id}）`;
  if (axios.isAxiosError(error) && error.response?.status === 401) return "登录已失效，请重新登录。";
  if (axios.isAxiosError(error) && error.response?.status === 404) return "企业或会话不存在，或您无权访问，请重新选择企业。";
  if (axios.isAxiosError(error) && error.response?.status === 422) return "提交内容格式不正确，请检查消息长度等输入信息。";
  return "暂时无法确认请求结果，请先查看我的工单。当前页面再次发送相同内容会复用原请求标识；刷新、切换会话或修改内容后，请先核对结果再提交。";
}
