<script setup lang="ts">
// 列表由 Query 管理并定期刷新；分页是本页面局部状态，不放入全局 Store。
import { computed, ref } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { listMyTickets } from "@/services/customer-service";
import CustomerTicketComments from "@/components/CustomerTicketComments.vue";
import TicketIssueDetails from "@/components/TicketIssueDetails.vue";

const page = ref(1);
const selectedTicketId = ref<string | null>(null);
const query = useQuery({
  queryKey: computed(() => ["customer-tickets", page.value]),
  queryFn: () => listMyTickets(page.value), refetchInterval: 15000,
});
const labels = { open: "待处理", in_progress: "处理中", waiting_customer: "等待客户", resolved: "已解决", closed: "已关闭" };
</script>

<template>
  <main class="portal-panel">
    <header class="portal-section-heading">
      <div><h1>我的工单</h1><p>查看处理进度。需要补充问题时，请返回在线咨询。</p></div><el-button
        :loading="query.isFetching.value"
        @click="query.refetch()"
      >
        刷新
      </el-button>
    </header>
    <el-alert
      v-if="query.isError.value"
      title="工单加载失败，请点击刷新重试"
      type="error"
      :closable="false"
    />
    <p v-if="query.isLoading.value">
      正在加载工单……
    </p>
    <el-empty
      v-else-if="!query.isError.value && !query.data.value?.items.length"
      description="暂无工单，您可以在在线咨询中描述问题并申请建单"
    />
    <article
      v-for="ticket in query.data.value?.items ?? []"
      :key="ticket.id"
      class="customer-ticket"
    >
      <div class="portal-section-heading">
        <strong>{{ ticket.code }} · {{ ticket.title }}</strong><el-tag>{{ labels[ticket.status] }}</el-tag>
      </div>
      <p class="ticket-company">
        服务企业：{{ ticket.company_name }}
      </p>
      <!-- 两端读取同一张工单的当前值，共用组件统一字段名称、顺序和长文本展示。 -->
      <TicketIssueDetails
        :description="ticket.description"
        :desired-resolution="ticket.desired_resolution"
        :impact-note="ticket.impact_note"
        :order="ticket.order"
      />
      <footer class="ticket-footer">
        <small>最近更新：{{ new Date(ticket.updated_at).toLocaleString('zh-CN') }}</small>
        <div class="ticket-actions">
          <!-- 保留链接的原生导航语义，但统一使用 Element Plus 的按钮尺寸与交互样式。 -->
          <RouterLink
            v-slot="{ href, navigate }"
            :to="'/customer/companies/' + ticket.company_id + '/chat'"
            custom
          >
            <el-button
              tag="a"
              :href="href"
              type="primary"
              @click="navigate"
            >
              联系该企业
            </el-button>
          </RouterLink>
          <el-button
            :aria-expanded="selectedTicketId === ticket.id"
            :aria-controls="`ticket-records-${ticket.id}`"
            @click="selectedTicketId = selectedTicketId === ticket.id ? null : ticket.id"
          >
            {{ selectedTicketId === ticket.id ? '收起修改与补充记录' : '查看修改与补充记录' }}
          </el-button>
        </div>
      </footer>
      <CustomerTicketComments
        v-if="selectedTicketId === ticket.id"
        :id="`ticket-records-${ticket.id}`"
        class="ticket-records"
        :ticket-id="ticket.id"
      />
    </article>
    <el-pagination
      v-if="(query.data.value?.total ?? 0) > 20"
      v-model:current-page="page"
      :page-size="20"
      :total="query.data.value?.total ?? 0"
      layout="prev, pager, next"
    />
  </main>
</template>

<style scoped>
.customer-ticket { margin-top: 20px; padding: 24px; border: 1px solid #e0e8e3; border-radius: 16px; background: #fff; }
.customer-ticket strong { overflow-wrap: anywhere; }
.ticket-company { margin: 0 0 22px; color: #748078; font-size: 13px; }
.ticket-footer { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px; margin-top: 24px; padding-top: 18px; border-top: 1px solid #edf1ee; }
.ticket-footer small { color: #748078; }
.ticket-actions { display: flex; flex-wrap: wrap; gap: 10px; }
.ticket-actions .el-button { margin: 0; min-height: 40px; height: auto; padding: 10px 16px; border-radius: 10px; font-size: 14px; text-decoration: none; }
.ticket-records { margin-top: 20px; padding: 18px; background: #f5f8f6; border-radius: 12px; }
@media (max-width: 600px) {
  .customer-ticket { padding: 18px; }
  .ticket-actions { width: 100%; }
  .ticket-actions .el-button { flex: 1 1 auto; }
}
</style>
