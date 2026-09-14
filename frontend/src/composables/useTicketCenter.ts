import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, reactive, ref } from "vue";
import { useRoute } from "vue-router";

import {
  addTicketNote,
  createTicket,
  getTicket,
  getTicketStatistics,
  listTickets,
  updateTicket,
} from "@/services/ticket-service";
import type { TicketFilters } from "@/types/ticket";

/** 管理工单中心的服务端状态；筛选条件是页面局部状态，不进入全局 Pinia。 */
export function useTicketCenter() {
  const route = useRoute();
  const queryClient = useQueryClient();
  const selectedTicketId = ref<string | null>(null);
  const filters = reactive<TicketFilters>({
    status: "",
    priority: "",
    keyword: "",
    page: 1,
    pageSize: 10,
  });

  const listQuery = useQuery({
    queryKey: computed(() => ["tickets", { ...filters }, route.query.customer_id]),
    queryFn: () => listTickets({ ...filters, customerId: typeof route.query.customer_id === "string" ? route.query.customer_id : undefined }),
  });
  const statisticsQuery = useQuery({
    queryKey: ["ticket-statistics"],
    queryFn: getTicketStatistics,
  });
  const detailQuery = useQuery({
    queryKey: computed(() => ["ticket", selectedTicketId.value]),
    queryFn: () => getTicket(selectedTicketId.value as string),
    enabled: computed(() => selectedTicketId.value !== null),
  });

  async function refreshTicketData(ticketId?: string): Promise<void> {
    // 修改成功后同时刷新列表、统计和详情，避免同一工单在不同区域显示不同状态。
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["tickets"] }),
      queryClient.invalidateQueries({ queryKey: ["ticket-statistics"] }),
      ticketId
        ? queryClient.invalidateQueries({ queryKey: ["ticket", ticketId] })
        : Promise.resolve(),
    ]);
  }

  const createMutation = useMutation({
    mutationFn: createTicket,
    async onSuccess(ticket) {
      selectedTicketId.value = ticket.id;
      await refreshTicketData(ticket.id);
    },
  });
  const updateMutation = useMutation({
    mutationFn: updateTicket,
    async onSuccess(ticket) {
      await refreshTicketData(ticket.id);
    },
  });
  const noteMutation = useMutation({
    mutationFn: addTicketNote,
    async onSuccess(ticket) {
      await refreshTicketData(ticket.id);
    },
  });

  function resetFilters(): void {
    Object.assign(filters, { status: "", priority: "", keyword: "", page: 1, pageSize: 10 });
  }

  return {
    filters,
    selectedTicketId,
    tickets: computed(() => listQuery.data.value?.items ?? []),
    total: computed(() => listQuery.data.value?.total ?? 0),
    statistics: statisticsQuery.data,
    selectedTicket: detailQuery.data,
    isLoadingList: listQuery.isFetching,
    isLoadingDetail: detailQuery.isFetching,
    listError: listQuery.error,
    detailError: detailQuery.error,
    createMutation,
    updateMutation,
    noteMutation,
    resetFilters,
  };
}
