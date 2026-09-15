<script setup lang="ts">
import {
  Activity,
  CheckCircle2,
  Clock3,
  RefreshCw,
  Search,
  Wrench,
  XCircle,
} from "@lucide/vue";
import { computed } from "vue";

import { useAgentRunCenter } from "@/composables/useAgentRunCenter";
import StaffNavigation from "@/components/StaffNavigation.vue";
import type { AgentRunStatus } from "@/types/agent-run";

const {
  filters,
  selectedRunId,
  runs,
  total,
  statistics,
  selectedRun,
  isLoadingList,
  isLoadingDetail,
  listError,
  detailError,
  refresh,
  resetFilters,
} = useAgentRunCenter();

const statusOptions: Array<{ label: string; value: AgentRunStatus }> = [
  { label: "运行中", value: "running" },
  { label: "成功", value: "succeeded" },
  { label: "失败", value: "failed" },
];
const intentLabels: Record<string, string> = {
  general: "通用咨询",
  account: "账号问题",
  order: "订单问题",
  ticket: "工单请求",
  complaint: "投诉建议",
};
const priorityLabels: Record<string, string> = {
  low: "低",
  medium: "中",
  high: "高",
  urgent: "紧急",
};

const successRate = computed(() => {
  const completed = (statistics.value?.succeeded ?? 0) + (statistics.value?.failed ?? 0);
  if (!completed) return "0%";
  return `${Math.round(((statistics.value?.succeeded ?? 0) / completed) * 100)}%`;
});
const statisticCards = computed(() => [
  { label: "累计运行", value: statistics.value?.total ?? 0, icon: Activity, tone: "all" },
  { label: "成功率", value: successRate.value, icon: CheckCircle2, tone: "success" },
  { label: "平均耗时", value: formatDuration(statistics.value?.average_duration_ms), icon: Clock3, tone: "time" },
  { label: "Tool 调用", value: statistics.value?.tool_calls ?? 0, icon: Wrench, tone: "tool" },
]);

function statusLabel(status: AgentRunStatus): string {
  return statusOptions.find((item) => item.value === status)?.label ?? status;
}

function formatDuration(value: number | null | undefined): string {
  if (value === null || value === undefined) return "--";
  return value >= 1000 ? `${(value / 1000).toFixed(2)} 秒` : `${value} ms`;
}

function formatDate(value: string | null): string {
  if (!value) return "--";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function shortId(value: string | null): string {
  return value ? `${value.slice(0, 8)}…` : "--";
}
</script>

<template>
  <main class="app-shell agent-run-page">
    <!-- 三个核心模块共享同一导航，运行记录作为独立页面而不是会话页内的临时弹窗。 -->
    <StaffNavigation />

    <section class="workspace agent-run-workspace">
      <header class="run-page-header">
        <div>
          <p class="eyebrow">
            Observability
          </p><h1>Agent 运行记录</h1><p>追踪模型判断、Tool 调用与异常请求</p>
        </div>
        <el-button @click="refresh">
          <RefreshCw :size="15" />刷新数据
        </el-button>
      </header>

      <!-- 卡片数据来自全量聚合接口，不受当前筛选和分页影响。 -->
      <section
        class="run-statistics"
        aria-label="Agent 运行统计"
      >
        <article
          v-for="card in statisticCards"
          :key="card.label"
          :class="`run-stat-card ${card.tone}`"
        >
          <div>
            <component
              :is="card.icon"
              :size="18"
            />
          </div>
          <span>{{ card.label }}</span><strong>{{ card.value }}</strong>
        </article>
      </section>

      <section class="run-list-card">
        <div class="run-filters">
          <el-input
            v-model="filters.keyword"
            clearable
            placeholder="搜索请求 ID、模型、Tool 或工单编号"
          >
            <template #prefix>
              <Search :size="15" />
            </template>
          </el-input>
          <el-select
            v-model="filters.status"
            placeholder="全部状态"
          >
            <el-option
              label="全部状态"
              value=""
            />
            <el-option
              v-for="item in statusOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
          <el-select
            v-model="filters.toolCalled"
            placeholder="全部调用"
          >
            <el-option
              label="全部调用"
              value=""
            />
            <el-option
              label="调用过 Tool"
              value="true"
            />
            <el-option
              label="未调用 Tool"
              value="false"
            />
          </el-select>
          <el-button @click="resetFilters">
            <RefreshCw :size="15" />重置
          </el-button>
        </div>
        <el-alert
          v-if="listError"
          title="运行记录加载失败，请检查后端服务和数据库迁移"
          type="error"
          :closable="false"
          show-icon
        />

        <!-- 列表只展示高频诊断字段，完整请求 ID 和失败原因在详情抽屉中按需读取。 -->
        <el-table
          v-loading="isLoadingList"
          :data="runs"
          row-key="id"
          empty-text="暂无 Agent 运行记录，发送一条客户消息后会自动生成"
          class="run-table"
          @row-click="(row) => selectedRunId = row.id"
        >
          <el-table-column
            label="开始时间"
            width="165"
          >
            <template #default="{ row }">
              {{ formatDate(row.started_at) }}
            </template>
          </el-table-column>
          <el-table-column
            label="状态"
            width="100"
          >
            <template #default="{ row }">
              <span :class="`run-status ${row.status}`">{{ statusLabel(row.status) }}</span>
            </template>
          </el-table-column>
          <el-table-column
            label="意图 / 优先级"
            min-width="150"
          >
            <template #default="{ row }">
              {{ intentLabels[row.intent] || row.intent || "分析中" }} · {{ priorityLabels[row.priority] || row.priority || "--" }}
            </template>
          </el-table-column>
          <el-table-column
            label="Tool"
            min-width="190"
          >
            <template #default="{ row }">
              <span
                v-if="row.tool_name"
                class="tool-name"
              ><Wrench :size="13" />{{ row.tool_name }}</span><span
                v-else
                class="muted-value"
              >未调用</span>
            </template>
          </el-table-column>
          <el-table-column
            label="工单"
            min-width="145"
          >
            <template #default="{ row }">
              {{ row.ticket_code || "--" }}
            </template>
          </el-table-column>
          <el-table-column
            label="耗时"
            width="100"
          >
            <template #default="{ row }">
              {{ formatDuration(row.duration_ms) }}
            </template>
          </el-table-column>
          <el-table-column
            label="请求 ID"
            width="115"
          >
            <template #default="{ row }">
              <span class="mono-value">{{ shortId(row.request_id) }}</span>
            </template>
          </el-table-column>
        </el-table>
        <div class="ticket-pagination">
          <span>共 {{ total }} 条记录</span>
          <el-pagination
            v-model:current-page="filters.page"
            v-model:page-size="filters.pageSize"
            :total="total"
            :page-sizes="[10, 20, 50]"
            layout="sizes, prev, pager, next"
          />
        </div>
      </section>
    </section>

    <!-- 详情抽屉展示可关联日志的字段，客户消息正文不会进入运行记录。 -->
    <el-drawer
      :model-value="selectedRunId !== null"
      size="min(560px, 100%)"
      destroy-on-close
      @close="selectedRunId = null"
    >
      <template #header>
        <div class="drawer-heading">
          <span>RUN {{ shortId(selectedRunId) }}</span><h2>运行详情</h2>
        </div>
      </template>
      <div
        v-loading="isLoadingDetail"
        class="run-detail"
      >
        <el-alert
          v-if="detailError"
          title="运行详情加载失败"
          type="error"
          :closable="false"
          show-icon
        />
        <template v-if="selectedRun">
          <div :class="`run-result-banner ${selectedRun.status}`">
            <CheckCircle2
              v-if="selectedRun.status === 'succeeded'"
              :size="20"
            />
            <XCircle
              v-else-if="selectedRun.status === 'failed'"
              :size="20"
            />
            <Clock3
              v-else
              :size="20"
            />
            <div><strong>{{ statusLabel(selectedRun.status) }}</strong><span>{{ formatDuration(selectedRun.duration_ms) }}</span></div>
          </div>
          <section class="run-detail-section">
            <h3>链路标识</h3>
            <dl>
              <div>
                <dt>请求 ID</dt><dd class="mono-value">
                  {{ selectedRun.request_id }}
                </dd>
              </div><div>
                <dt>运行 ID</dt><dd class="mono-value">
                  {{ selectedRun.id }}
                </dd>
              </div><div>
                <dt>会话 ID</dt><dd class="mono-value">
                  {{ selectedRun.conversation_id || "--" }}
                </dd>
              </div>
            </dl>
          </section>
          <section class="run-detail-section">
            <h3>模型判断</h3>
            <dl><div><dt>模型</dt><dd>{{ selectedRun.model_name }}</dd></div><div><dt>意图</dt><dd>{{ intentLabels[selectedRun.intent || ""] || selectedRun.intent || "--" }}</dd></div><div><dt>优先级</dt><dd>{{ priorityLabels[selectedRun.priority || ""] || selectedRun.priority || "--" }}</dd></div><div><dt>需要人工</dt><dd>{{ selectedRun.requires_human === null ? "--" : selectedRun.requires_human ? "是" : "否" }}</dd></div></dl>
            <p
              v-if="selectedRun.decision_reason"
              class="decision-reason"
            >
              {{ selectedRun.decision_reason }}
            </p>
          </section>
          <section class="run-detail-section">
            <h3>Tool 执行</h3>
            <div
              v-if="selectedRun.tool_name"
              class="tool-result"
            >
              <Wrench :size="17" /><div><strong>{{ selectedRun.tool_name }}</strong><span>{{ selectedRun.tool_name === "query_support_tickets" ? "已完成只读工单查询" : `已创建 ${selectedRun.ticket_code}` }}</span></div>
            </div>
            <p
              v-else
              class="empty-run-detail"
            >
              本次运行没有调用业务 Tool
            </p>
          </section>
          <section
            v-if="selectedRun.status === 'failed'"
            class="run-detail-section error-detail"
          >
            <h3>失败信息</h3><strong>{{ selectedRun.error_type }}</strong><p>{{ selectedRun.error_message }}</p>
          </section>
        </template>
      </div>
    </el-drawer>
  </main>
</template>
