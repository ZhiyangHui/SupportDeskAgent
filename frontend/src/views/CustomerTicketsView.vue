<script setup lang="ts">
// 列表由 Query 管理并定期刷新；分页是本页面局部状态，不放入全局 Store。
import { computed, ref } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { listMyTickets } from "@/services/customer-service";

const page = ref(1);
const query = useQuery({
  queryKey: computed(() => ["customer-tickets", page.value]),
  queryFn: () => listMyTickets(page.value), refetchInterval: 15000,
});
const labels = { open: "待处理", in_progress: "处理中", waiting_customer: "等待补充信息", resolved: "已解决", closed: "已关闭" };
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
      <p>服务企业：{{ ticket.company_name }}</p><p>{{ ticket.description }}</p><small>最近更新：{{ new Date(ticket.updated_at).toLocaleString('zh-CN') }}</small>
      <RouterLink
        class="portal-action-link"
        :to="'/customer/companies/' + ticket.company_id + '/chat'"
      >
        联系该企业
      </RouterLink>
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
