<script setup lang="ts">
import {
  ArrowLeft,
  ClipboardList,
  Headphones,
  MessageSquareText,
  Plus,
  RefreshCw,
  Search,
  TicketCheck,
} from "@lucide/vue";
import { isAxiosError } from "axios";
import { ElMessage } from "element-plus";
import { computed, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { useTicketCenter } from "@/composables/useTicketCenter";
import {
  createTicketInputSchema,
  type CreateTicketInput,
  type TicketActivityType,
  type TicketPriority,
  type TicketStatus,
} from "@/types/ticket";

const route = useRoute();
const router = useRouter();
const operatorName = "客服专员";

const {
  filters,
  selectedTicketId,
  tickets,
  total,
  statistics,
  selectedTicket,
  isLoadingList,
  isLoadingDetail,
  listError,
  detailError,
  createMutation,
  updateMutation,
  noteMutation,
  resetFilters,
} = useTicketCenter();

const createDialogVisible = ref(false);
const createFormError = ref<string | null>(null);
const noteContent = ref("");
const assigneeDraft = ref("");
const createForm = reactive<CreateTicketInput>({
  title: "",
  description: "",
  category: "general",
  priority: "medium",
  conversation_id: null,
  customer_name: "",
  customer_email: "",
  operator_name: operatorName,
});

const statusOptions: Array<{ label: string; value: TicketStatus }> = [
  { label: "待处理", value: "open" },
  { label: "处理中", value: "in_progress" },
  { label: "等待客户", value: "waiting_customer" },
  { label: "已解决", value: "resolved" },
  { label: "已关闭", value: "closed" },
];
const priorityOptions: Array<{ label: string; value: TicketPriority }> = [
  { label: "低", value: "low" },
  { label: "中", value: "medium" },
  { label: "高", value: "high" },
  { label: "紧急", value: "urgent" },
];
const categoryOptions = [
  { label: "通用咨询", value: "general" },
  { label: "账号与权限", value: "account" },
  { label: "订单与支付", value: "billing" },
  { label: "产品故障", value: "technical" },
  { label: "投诉与建议", value: "complaint" },
];

// 状态选项来自后端同一套业务规则，用于提前阻止无效操作；后端仍会做最终校验。
const allowedTransitions: Record<TicketStatus, TicketStatus[]> = {
  open: ["in_progress", "closed"],
  in_progress: ["waiting_customer", "resolved", "closed"],
  waiting_customer: ["in_progress", "resolved", "closed"],
  resolved: ["in_progress", "closed"],
  closed: [],
};
const availableStatusOptions = computed(() => {
  const current = selectedTicket.value?.status;
  if (!current) return [];
  return statusOptions.filter(
    (option) => option.value === current || allowedTransitions[current].includes(option.value),
  );
});

const statisticsCards = computed(() => [
  { label: "全部工单", value: statistics.value?.total ?? 0, tone: "all" },
  { label: "待处理", value: statistics.value?.open ?? 0, tone: "open" },
  { label: "处理中", value: statistics.value?.in_progress ?? 0, tone: "progress" },
  { label: "等待客户", value: statistics.value?.waiting_customer ?? 0, tone: "waiting" },
]);

function statusLabel(status: TicketStatus): string {
  return statusOptions.find((item) => item.value === status)?.label ?? status;
}

function priorityLabel(priority: TicketPriority): string {
  return priorityOptions.find((item) => item.value === priority)?.label ?? priority;
}

function categoryLabel(category: string): string {
  return categoryOptions.find((item) => item.value === category)?.label ?? category;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function activityTitle(type: TicketActivityType): string {
  return {
    created: "创建工单",
    status_changed: "更新处理状态",
    priority_changed: "调整优先级",
    assigned: "变更负责人",
    note_added: "添加内部备注",
  }[type];
}

function activityDescription(activity: NonNullable<typeof selectedTicket.value>["activities"][number]): string {
  if (activity.activity_type === "note_added") return activity.content ?? "已添加备注";
  if (activity.activity_type === "status_changed") {
    return `${statusLabel(activity.from_value as TicketStatus)} → ${statusLabel(activity.to_value as TicketStatus)}`;
  }
  if (activity.activity_type === "priority_changed") {
    return `${priorityLabel(activity.from_value as TicketPriority)} → ${priorityLabel(activity.to_value as TicketPriority)}`;
  }
  if (activity.activity_type === "assigned") {
    return activity.to_value ? `负责人变更为 ${activity.to_value}` : "已取消客服指派";
  }
  return activity.content ?? "工单已进入处理队列";
}

function mutationErrorMessage(error: unknown): string {
  // 422、404 等预期错误优先展示后端的稳定 detail，方便用户直接修正具体字段。
  // 未知异常仍退回通用消息，避免把堆栈或内部实现细节暴露在页面中。
  if (isAxiosError(error)) {
    const responseData: unknown = error.response?.data;
    if (typeof responseData === "object" && responseData !== null && "detail" in responseData) {
      const detail = responseData.detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        const firstError: unknown = detail[0];
        if (typeof firstError === "object" && firstError !== null && "msg" in firstError) {
          return String(firstError.msg);
        }
      }
    }
  }
  return error instanceof Error ? error.message : "操作失败，请稍后重试";
}

function openTicket(ticketId: string): void {
  selectedTicketId.value = ticketId;
}

function openCreateDialog(): void {
  // 从会话页跳转时携带 conversation_id，实现“当前会话转工单”，普通入口保持为空。
  createForm.conversation_id =
    typeof route.query.conversation_id === "string" ? route.query.conversation_id : null;
  createFormError.value = null;
  createDialogVisible.value = true;
}

function resetCreateForm(): void {
  Object.assign(createForm, {
    title: "",
    description: "",
    category: "general",
    priority: "medium",
    conversation_id: null,
    customer_name: "",
    customer_email: "",
    operator_name: operatorName,
  });
}

async function submitCreate(): Promise<void> {
  createFormError.value = null;
  const result = createTicketInputSchema.safeParse(createForm);
  if (!result.success) {
    createFormError.value = result.error.issues[0]?.message ?? "请检查工单内容";
    ElMessage.warning(createFormError.value);
    return;
  }

  try {
    await createMutation.mutateAsync(result.data);
    createDialogVisible.value = false;
    ElMessage.success("工单创建成功");
    // 消费一次性 query 参数后清理地址，刷新页面时不会重复弹出创建窗口。
    if (route.query.create) await router.replace({ name: "ticket-center" });
    resetCreateForm();
  } catch (error) {
    createFormError.value = mutationErrorMessage(error);
    ElMessage.error(createFormError.value);
  }
}

async function changeStatus(value: TicketStatus): Promise<void> {
  if (!selectedTicket.value || value === selectedTicket.value.status) return;
  try {
    await updateMutation.mutateAsync({
      id: selectedTicket.value.id,
      status: value,
      operator_name: operatorName,
    });
    ElMessage.success("工单状态已更新");
  } catch (error) {
    ElMessage.error(mutationErrorMessage(error));
  }
}

async function changePriority(value: TicketPriority): Promise<void> {
  if (!selectedTicket.value || value === selectedTicket.value.priority) return;
  try {
    await updateMutation.mutateAsync({
      id: selectedTicket.value.id,
      priority: value,
      operator_name: operatorName,
    });
    ElMessage.success("工单优先级已更新");
  } catch (error) {
    ElMessage.error(mutationErrorMessage(error));
  }
}

async function saveAssignee(): Promise<void> {
  if (!selectedTicket.value) return;
  try {
    await updateMutation.mutateAsync({
      id: selectedTicket.value.id,
      assignee_name: assigneeDraft.value.trim() || null,
      operator_name: operatorName,
    });
    ElMessage.success(assigneeDraft.value.trim() ? "负责人已更新" : "已取消指派");
  } catch (error) {
    ElMessage.error(mutationErrorMessage(error));
  }
}

async function submitNote(): Promise<void> {
  const content = noteContent.value.trim();
  if (!selectedTicket.value || !content) {
    ElMessage.warning("请先输入处理备注");
    return;
  }
  try {
    await noteMutation.mutateAsync({
      id: selectedTicket.value.id,
      content,
      operator_name: operatorName,
    });
    noteContent.value = "";
    ElMessage.success("内部备注已保存");
  } catch (error) {
    ElMessage.error(mutationErrorMessage(error));
  }
}

watch(
  () => [filters.status, filters.priority, filters.keyword],
  () => {
    // 更换筛选条件后回到第一页，防止旧页码在新结果集中形成看似“无数据”的空页。
    filters.page = 1;
  },
);
watch(
  selectedTicket,
  (ticket) => {
    assigneeDraft.value = ticket?.assignee_name ?? "";
  },
  { immediate: true },
);
watch(
  () => route.query.create,
  (shouldCreate) => {
    if (shouldCreate === "1") openCreateDialog();
  },
  { immediate: true },
);
watch(
  () => route.query.ticket_id,
  (ticketId) => {
    // 会话侧栏跳转过来时直接打开指定详情，省去客服再次在列表中查找。
    if (typeof ticketId === "string") selectedTicketId.value = ticketId;
  },
  { immediate: true },
);
</script>

<template>
  <main class="app-shell ticket-page-shell">
    <!-- 工单中心复用统一导航结构，让客服在会话与异步工单之间切换时不会失去位置感。 -->
    <aside
      class="sidebar"
      aria-label="工作台导航"
    >
      <div class="brand">
        <div class="brand-mark">
          <Headphones :size="21" />
        </div>
        <div><strong>SupportDesk</strong><span>智能客服工作台</span></div>
      </div>
      <nav class="nav-list">
        <RouterLink
          class="nav-item"
          to="/"
        >
          <MessageSquareText :size="18" />客户会话
        </RouterLink>
        <RouterLink
          class="nav-item active"
          to="/tickets"
        >
          <TicketCheck :size="18" />工单中心
        </RouterLink>
      </nav>
      <div class="sidebar-status">
        <span class="status-dot" />
        <div><strong>工单服务正常</strong><span>数据已连接 PostgreSQL</span></div>
      </div>
    </aside>

    <section class="workspace ticket-workspace">
      <header class="ticket-topbar">
        <div>
          <RouterLink
            class="back-link"
            to="/"
          >
            <ArrowLeft :size="15" />返回客户会话
          </RouterLink>
          <h1>工单中心</h1>
          <p>统一跟踪客户问题、处理进度与责任人</p>
        </div>
        <el-button
          type="primary"
          size="large"
          @click="openCreateDialog"
        >
          <Plus :size="16" />新建工单
        </el-button>
      </header>

      <!-- 统计数据由后端聚合，前端不依赖当前分页自行推算，保证全局数量准确。 -->
      <section
        class="ticket-statistics"
        aria-label="工单统计"
      >
        <article
          v-for="card in statisticsCards"
          :key="card.label"
          :class="`stat-card ${card.tone}`"
        >
          <span>{{ card.label }}</span><strong>{{ card.value }}</strong>
        </article>
      </section>

      <section class="ticket-list-card">
        <div class="ticket-filters">
          <el-input
            v-model="filters.keyword"
            clearable
            placeholder="搜索编号、标题或客户"
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
            v-model="filters.priority"
            placeholder="全部优先级"
          >
            <el-option
              label="全部优先级"
              value=""
            />
            <el-option
              v-for="item in priorityOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
          <el-button @click="resetFilters">
            <RefreshCw :size="15" />重置
          </el-button>
        </div>

        <el-alert
          v-if="listError"
          title="工单列表加载失败，请确认后端与数据库已启动"
          type="error"
          :closable="false"
          show-icon
        />

        <!-- 表格只展示摘要；点击一行时才按需请求详情和审计记录，控制首屏数据量。 -->
        <el-table
          v-loading="isLoadingList"
          :data="tickets"
          row-key="id"
          empty-text="暂无符合条件的工单"
          class="ticket-table"
          @row-click="(row) => openTicket(row.id)"
        >
          <el-table-column
            label="工单"
            min-width="260"
          >
            <template #default="{ row }">
              <div class="ticket-primary-cell">
                <strong>{{ row.title }}</strong><span>{{ row.code }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column
            label="客户"
            min-width="130"
          >
            <template #default="{ row }">
              {{ row.customer_name || "未填写" }}
            </template>
          </el-table-column>
          <el-table-column
            label="分类"
            min-width="120"
          >
            <template #default="{ row }">
              {{ categoryLabel(row.category) }}
            </template>
          </el-table-column>
          <el-table-column
            label="优先级"
            width="100"
          >
            <template #default="{ row }">
              <el-tag
                :class="`priority-tag ${row.priority}`"
                effect="plain"
              >
                {{ priorityLabel(row.priority) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column
            label="状态"
            width="120"
          >
            <template #default="{ row }">
              <span :class="`status-pill ${row.status}`">{{ statusLabel(row.status) }}</span>
            </template>
          </el-table-column>
          <el-table-column
            label="负责人"
            min-width="120"
          >
            <template #default="{ row }">
              {{ row.assignee_name || "待分配" }}
            </template>
          </el-table-column>
          <el-table-column
            label="最后更新"
            width="135"
          >
            <template #default="{ row }">
              {{ formatDate(row.updated_at) }}
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

    <!-- 抽屉中的所有修改均调用后端 Service；成功后 Query 会统一刷新列表、统计和当前详情。 -->
    <el-drawer
      :model-value="selectedTicketId !== null"
      size="min(620px, 100%)"
      destroy-on-close
      @close="selectedTicketId = null"
    >
      <template #header>
        <div
          v-if="selectedTicket"
          class="drawer-heading"
        >
          <span>{{ selectedTicket.code }}</span><h2>{{ selectedTicket.title }}</h2>
        </div>
      </template>
      <div
        v-loading="isLoadingDetail"
        class="ticket-detail"
      >
        <el-alert
          v-if="detailError"
          title="工单详情加载失败，记录可能已被删除或服务暂时不可用"
          type="error"
          :closable="false"
          show-icon
        />
        <template v-if="selectedTicket">
          <section class="detail-section detail-overview">
            <div><span>客户</span><strong>{{ selectedTicket.customer_name || "未填写" }}</strong></div>
            <div><span>邮箱</span><strong>{{ selectedTicket.customer_email || "未填写" }}</strong></div>
            <div><span>来源</span><strong>{{ selectedTicket.source === "agent" ? "会话转单" : "人工创建" }}</strong></div>
            <div><span>分类</span><strong>{{ categoryLabel(selectedTicket.category) }}</strong></div>
          </section>

          <section class="detail-section">
            <h3>问题描述</h3><p class="ticket-description">
              {{ selectedTicket.description }}
            </p>
          </section>

          <section class="detail-section operation-grid">
            <label><span>处理状态</span>
              <el-select
                :model-value="selectedTicket.status"
                :loading="updateMutation.isPending.value"
                @change="changeStatus"
              >
                <el-option
                  v-for="item in availableStatusOptions"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </el-select>
            </label>
            <label><span>优先级</span>
              <el-select
                :model-value="selectedTicket.priority"
                :loading="updateMutation.isPending.value"
                @change="changePriority"
              >
                <el-option
                  v-for="item in priorityOptions"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </el-select>
            </label>
            <label class="assignee-field"><span>负责人</span>
              <div><el-input
                v-model="assigneeDraft"
                clearable
                placeholder="留空表示取消指派"
              /><el-button
                :loading="updateMutation.isPending.value"
                @click="saveAssignee"
              >保存</el-button></div>
            </label>
          </section>

          <section class="detail-section">
            <h3>内部处理备注</h3>
            <el-input
              v-model="noteContent"
              type="textarea"
              :rows="3"
              maxlength="5000"
              show-word-limit
              placeholder="记录排查结果、客户回访或下一步动作"
            />
            <div class="note-action">
              <el-button
                type="primary"
                :loading="noteMutation.isPending.value"
                @click="submitNote"
              >
                保存备注
              </el-button>
            </div>
          </section>

          <section class="detail-section">
            <h3>操作记录</h3>
            <el-timeline class="activity-timeline">
              <el-timeline-item
                v-for="activity in [...selectedTicket.activities].reverse()"
                :key="activity.id"
                :timestamp="formatDate(activity.created_at)"
                placement="top"
              >
                <strong>{{ activityTitle(activity.activity_type) }}</strong>
                <p>{{ activityDescription(activity) }}</p>
                <small>操作人：{{ activity.operator_name }}</small>
              </el-timeline-item>
            </el-timeline>
          </section>
        </template>
      </div>
    </el-drawer>

    <!-- 新建弹窗提供业务必填项，输入在提交前由 Zod 校验，后端再执行最终领域校验。 -->
    <el-dialog
      v-model="createDialogVisible"
      title="新建客户工单"
      width="min(620px, 92vw)"
      @closed="resetCreateForm"
    >
      <el-form label-position="top">
        <!-- 校验原因固定显示在表单内，避免短暂提示让用户误以为按钮没有响应。 -->
        <el-alert
          v-if="createFormError"
          class="create-form-error"
          :title="createFormError"
          type="error"
          :closable="false"
          show-icon
        />
        <el-form-item
          label="工单标题"
          required
        >
          <el-input
            v-model="createForm.title"
            maxlength="200"
            show-word-limit
            placeholder="一句话概括客户问题"
          />
        </el-form-item>
        <div class="create-form-grid">
          <el-form-item
            label="问题分类"
            required
          >
            <el-select v-model="createForm.category">
              <el-option
                v-for="item in categoryOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item
            label="优先级"
            required
          >
            <el-select v-model="createForm.priority">
              <el-option
                v-for="item in priorityOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </el-form-item>
        </div>
        <div class="create-form-grid">
          <el-form-item label="客户姓名">
            <el-input
              v-model="createForm.customer_name"
              placeholder="选填"
            />
          </el-form-item>
          <el-form-item label="客户邮箱">
            <el-input
              v-model="createForm.customer_email"
              placeholder="选填"
            />
          </el-form-item>
        </div>
        <el-form-item
          v-if="createForm.conversation_id"
          label="关联会话"
        >
          <el-input
            v-model="createForm.conversation_id"
            disabled
          />
        </el-form-item>
        <el-form-item
          label="问题描述"
          required
        >
          <el-input
            v-model="createForm.description"
            type="textarea"
            :rows="5"
            maxlength="10000"
            show-word-limit
            placeholder="描述问题现象、影响范围和客户诉求"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button
          native-type="button"
          @click="createDialogVisible = false"
        >
          取消
        </el-button>
        <el-button
          type="primary"
          native-type="button"
          :loading="createMutation.isPending.value"
          @click="submitCreate"
        >
          <ClipboardList :size="15" />创建并进入处理
        </el-button>
      </template>
    </el-dialog>
  </main>
</template>
