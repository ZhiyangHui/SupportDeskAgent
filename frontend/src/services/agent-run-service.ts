import { httpClient } from "@/lib/http";
import {
  agentRunListSchema,
  agentRunSchema,
  agentRunStatisticsSchema,
  type AgentRun,
  type AgentRunFilters,
  type AgentRunList,
  type AgentRunStatistics,
} from "@/types/agent-run";

/** 查询运行记录摘要，空筛选条件不进入 URL，避免后端枚举收到空字符串。 */
export async function listAgentRuns(filters: AgentRunFilters): Promise<AgentRunList> {
  const response = await httpClient.get<unknown>("/api/v1/agent-runs", {
    params: {
      status: filters.status || undefined,
      tool_called: filters.toolCalled || undefined,
      keyword: filters.keyword.trim() || undefined,
      offset: (filters.page - 1) * filters.pageSize,
      limit: filters.pageSize,
    },
  });
  return agentRunListSchema.parse(response.data);
}

export async function getAgentRun(runId: string): Promise<AgentRun> {
  const response = await httpClient.get<unknown>(
    `/api/v1/agent-runs/${encodeURIComponent(runId)}`,
  );
  return agentRunSchema.parse(response.data);
}

export async function getAgentRunStatistics(): Promise<AgentRunStatistics> {
  const response = await httpClient.get<unknown>("/api/v1/agent-runs/statistics");
  return agentRunStatisticsSchema.parse(response.data);
}
