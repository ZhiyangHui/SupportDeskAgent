import { z } from "zod";
import { httpClient } from "@/lib/http";

const sourceKind = z.enum(["document", "ticket_case"]).default("document");
const documentSchema = z.object({ id: z.string().uuid(), title: z.string(), published: z.boolean(), chunk_count: z.number(), created_at: z.string(), source_kind: sourceKind });
const hitSchema = z.object({ document_id: z.string().uuid(), chunk_id: z.string().uuid(), title: z.string(), position: z.number(), content: z.string(), score: z.number(), source_kind: sourceKind });
export interface TicketExperienceInput {
  ticket_code: string; title: string; symptom: string; cause: string; solution: string; applicability: string;
}
const experienceOption = z.object({ code: z.string(), title: z.string(), status: z.enum(["resolved", "closed"]) });
const experienceSource = experienceOption.extend({ description: z.string(), desired_resolution: z.string(), impact_note: z.string() });
export async function listExperienceTickets(keyword: string, page: number) {
  return z.array(experienceOption).parse((await httpClient.get("/api/v1/staff/knowledge/ticket-experiences/candidates", { params: { keyword, offset: (page - 1) * 20 } })).data);
}
export async function getExperienceTicket(code: string) {
  return experienceSource.parse((await httpClient.get("/api/v1/staff/knowledge/ticket-experiences/source", { params: { code } })).data);
}
// 只提交员工整理的通用经验，不从工单接口自动复制客户信息或内部备注。
export async function createTicketExperience(input: TicketExperienceInput) {
  return documentSchema.parse((await httpClient.post("/api/v1/staff/knowledge/ticket-experiences", input)).data);
}
// 详情中的片段来自数据库，区别于检索测试中仅命中的部分片段。
const detailSchema = documentSchema.extend({ content: z.string(), chunks: z.array(z.object({
  id: z.string().uuid(), position: z.number(), content: z.string(), heading_path: z.string().default(""), version: z.number().default(0),
})), draft_chunks: z.array(z.object({ heading_path: z.string(), content: z.string() })).default([]),
draft_revision: z.number().default(0), published_revision: z.number().default(0), draft_warnings: z.array(z.string()).default([]),
source_ticket_id: z.string().uuid().nullable().optional(), reviewed_at: z.string().nullable().optional() });
export type KnowledgeDetail = z.infer<typeof detailSchema>;
export async function prepareKnowledge(id: string, revision: number) {
  await httpClient.post(`/api/v1/staff/knowledge/${id}/preview`, { revision });
}
export async function saveKnowledgeDraft(id: string, revision: number, chunks: KnowledgeDetail["draft_chunks"]) {
  await httpClient.put(`/api/v1/staff/knowledge/${id}/draft`, { revision, chunks });
}
export async function getKnowledge(id: string) {
  return detailSchema.parse((await httpClient.get(`/api/v1/staff/knowledge/${id}`)).data);
}
// 所有接口仅使用员工会话，企业 ID 不能通过前端参数指定。
export async function listKnowledge(page: number) {
  return z.array(documentSchema).parse((await httpClient.get("/api/v1/staff/knowledge", { params: { offset: (page - 1) * 20 } })).data);
}
export async function createKnowledge(title: string, content: string) {
  await httpClient.post("/api/v1/staff/knowledge", { title, content });
}
export async function uploadKnowledge(file: File) {
  const form = new FormData();
  form.append("file", file);
  await httpClient.post("/api/v1/staff/knowledge/upload", form);
}
export async function changeKnowledge(id: string, action: "publish" | "disable", revision?: number, confirmCaseReview = false) {
  await httpClient.post(`/api/v1/staff/knowledge/${id}/${action}`, { revision, confirm_case_review: confirmCaseReview }, { timeout: 45000 });
}
export async function searchKnowledge(query: string) {
  return z.array(hitSchema).parse((await httpClient.post("/api/v1/staff/knowledge/search", { query }, { timeout: 35000 })).data);
}
