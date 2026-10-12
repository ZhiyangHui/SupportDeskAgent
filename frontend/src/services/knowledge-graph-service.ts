// 前端只读取后端发布的领域知识，不再提交节点、关系或文档审核操作。
import { z } from "zod";
import { isAxiosError } from "axios";
import { httpClient } from "@/lib/http";

const concept = z.object({
  id: z.string(), kind: z.enum(["category", "symptom", "cause", "check", "solution", "condition"]),
  name: z.string(), description: z.string(),
});
const path = z.object({
  id: z.string(), category: z.string(), symptom: z.string(), cause: z.string(),
  checks: z.array(z.string()), solution: z.string(), requires: z.array(z.string()), excludes: z.array(z.string()),
  explanation: z.string(), escalation: z.string(),
});
const catalog = z.object({
  id: z.string(), version: z.number().int(), title: z.string(), maturity: z.enum(["demo", "verified"]),
  provenance: z.string(), nodes: z.array(concept), paths: z.array(path),
});
export type DomainCatalog = z.infer<typeof catalog>;
export const kindLabels = { category: "产品类别", symptom: "问题现象", cause: "可能原因", check: "核实步骤", solution: "处理方案", condition: "适用条件" };
export async function getDomainCatalog() {
  return catalog.parse((await httpClient.get("/api/v1/staff/knowledge-graph/catalog")).data);
}
export function graphError(error: unknown) {
  const detail = isAxiosError(error) ? error.response?.data?.detail : null;
  return typeof detail === "string" ? detail : "未能读取领域知识，请检查服务并重试。";
}
