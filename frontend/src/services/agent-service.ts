import { httpClient } from "@/lib/http";
import { agentChatResponseSchema, type AgentChatResponse } from "@/types/agent";

/** 调用客服 Agent，并在外部数据进入业务状态前完成运行时校验。 */
export async function sendAgentMessage(message: string): Promise<AgentChatResponse> {
    // 请求字段必须与后端 ChatRequest 保持一致，Service 是前端唯一了解该协议的位置。
    const response = await httpClient.post<unknown>("/api/v1/agent/chat", { message });
    return agentChatResponseSchema.parse(response.data);
}
