import { useQuery } from "@tanstack/vue-query";
import { computed, reactive, ref, watch } from "vue";

import {
  getAgentRun,
  getAgentRunStatistics,
  listAgentRuns,
} from "@/services/agent-run-service";
import type { AgentRunFilters } from "@/types/agent-run";

/** Agent 运行记录是服务端事实，统一交给 TanStack Query 管理缓存和加载状态。 */
export function useAgentRunCenter() {
  const selectedRunId = ref<string | null>(null);
  const filters = reactive<AgentRunFilters>({
    status: "",
    toolCalled: "",
    keyword: "",
    page: 1,
    pageSize: 10,
  });
  const listQuery = useQuery({
    queryKey: computed(() => ["agent-runs", { ...filters }]),
    queryFn: () => listAgentRuns({ ...filters }),
    // 页面停留期间定时刷新，可以观察耗时较长的 running 记录最终成功或失败。
    refetchInterval: 10_000,
  });
  const statisticsQuery = useQuery({
    queryKey: ["agent-run-statistics"],
    queryFn: getAgentRunStatistics,
    refetchInterval: 10_000,
  });
  const detailQuery = useQuery({
    queryKey: computed(() => ["agent-run", selectedRunId.value]),
    queryFn: () => getAgentRun(selectedRunId.value as string),
    enabled: computed(() => selectedRunId.value !== null),
  });

  watch(
    () => [filters.status, filters.toolCalled, filters.keyword],
    () => {
      filters.page = 1;
    },
  );

  function resetFilters(): void {
    Object.assign(filters, {
      status: "",
      toolCalled: "",
      keyword: "",
      page: 1,
      pageSize: 10,
    });
  }

  function refresh(): void {
    // 手动刷新同时更新列表和统计，避免顶部数字与表格记录短暂不一致。
    void Promise.all([listQuery.refetch(), statisticsQuery.refetch()]);
  }

  return {
    filters,
    selectedRunId,
    runs: computed(() => listQuery.data.value?.items ?? []),
    total: computed(() => listQuery.data.value?.total ?? 0),
    statistics: statisticsQuery.data,
    selectedRun: detailQuery.data,
    isLoadingList: listQuery.isFetching,
    isLoadingDetail: detailQuery.isFetching,
    listError: listQuery.error,
    detailError: detailQuery.error,
    refresh,
    resetFilters,
  };
}
