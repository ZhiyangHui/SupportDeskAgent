<script setup lang="ts">
// 一级待办直接接管并打开回复抽屉，不需要先选择客户、再寻找历史会话。
import { computed, ref, watch } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { isAxiosError } from "axios";
import { changeHandoff, listHandoffs } from "@/services/handoff-service";
import { getStaffMessages } from "@/services/staff-customer-service";
import HandoffControls from "@/components/HandoffControls.vue";

const scope = ref<"pending" | "mine">("pending");
const page = ref(1);
const opened = ref<string | null>(null);
const drawer = ref(false);
const cache = useQueryClient();
watch(scope, () => { page.value = 1; });
const queue = useQuery({ queryKey: computed(() => ["handoff-queue", scope.value, page.value]),
  queryFn: () => listHandoffs(scope.value, page.value), refetchInterval: 3000, retry: false });
const messages = useQuery({ queryKey: computed(() => ["staff-conversation", opened.value]),
  queryFn: () => getStaffMessages(opened.value as string), enabled: computed(() => drawer.value && !!opened.value), refetchInterval: 3000 });
// 接口历史按时间正序返回；复制后倒序展示，不能反转共享 Query 缓存。
const newestMessages = computed(() => [...(messages.data.value ?? [])].reverse());
function open(id: string) { opened.value = id; drawer.value = true; }
const takeover = useMutation({
  mutationFn: (id: string) => changeHandoff(id, "takeover"),
  async onSuccess(_data, id) {
    await cache.invalidateQueries({ queryKey: ["staff-handoff", id] });
    open(id);
  },
  onSettled: () => cache.invalidateQueries({ queryKey: ["handoff-queue"] }),
});
const error = computed(() => {
  const value = takeover.error.value;
  const detail = isAxiosError(value) ? value.response?.data?.detail : null;
  return value ? (typeof detail === "string" ? detail : "接管失败，请刷新队列后重试。") : "";
});
</script>

<template>
  <section
    id="handoff-inbox"
    class="handoff-inbox"
    aria-label="人工接管待办"
  >
    <header class="inbox-header">
      <div><span class="inbox-eyebrow">客服优先待办</span><h2>人工接管工作区</h2><p>需要人工处理的会话直接显示在这里，点击接管即可回复。</p></div>
      <el-button @click="queue.refetch()">
        刷新队列
      </el-button>
    </header>
    <div class="inbox-tabs">
      <el-button
        :type="scope === 'pending' ? 'primary' : 'default'"
        @click="scope = 'pending'"
      >
        待人工接管
      </el-button>
      <el-button
        :type="scope === 'mine' ? 'primary' : 'default'"
        @click="scope = 'mine'"
      >
        我正在接待
      </el-button>
      <span
        v-if="queue.data.value"
        role="status"
      >共 {{ queue.data.value.total }} 段会话 · 每 3 秒更新</span>
    </div>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
    />
    <p v-if="queue.isLoading.value">
      正在读取接管队列……
    </p>
    <el-alert
      v-else-if="queue.isError.value"
      title="接管队列加载失败，请点击刷新队列重试"
      type="error"
      :closable="false"
    />
    <p
      v-else-if="!queue.data.value?.total"
      class="inbox-empty"
    >
      {{ scope === 'pending' ? '暂无待接管会话。客户申请人工或 Agent 判断需要人工后，会自动出现在这里。' : '您尚未接管会话。' }}
    </p>
    <article
      v-for="item in queue.data.value?.items ?? []"
      :key="item.conversation_id"
      class="handoff-card"
    >
      <div class="handoff-card-content">
        <div class="handoff-card-title">
          <strong>{{ item.customer_name }}</strong><el-tag :type="scope === 'pending' ? 'warning' : 'success'">
            {{ scope === 'pending' ? '等待人工接管' : '由我接待中' }}
          </el-tag>
        </div>
        <p>{{ item.reason }}</p>
        <small>{{ item.requested_at ? '申请时间：' + new Date(item.requested_at).toLocaleString('zh-CN') : '客服主动接管' }} · 会话 {{ item.conversation_id.slice(0, 8) }}</small>
      </div>
      <el-button
        v-if="scope === 'pending'"
        type="primary"
        size="large"
        :loading="takeover.isPending.value && takeover.variables.value === item.conversation_id"
        :disabled="takeover.isPending.value"
        @click="takeover.mutate(item.conversation_id)"
      >
        立即接管并回复
      </el-button>
      <el-button
        v-else
        type="primary"
        size="large"
        @click="open(item.conversation_id)"
      >
        继续回复
      </el-button>
    </article>
    <div
      v-if="(queue.data.value?.total ?? 0) > 20 || page > 1"
      class="inbox-tabs"
    >
      <el-button
        :disabled="page === 1"
        @click="page--"
      >
        上一页
      </el-button><span>第 {{ page }} 页</span><el-button
        :disabled="page * 20 >= (queue.data.value?.total ?? 0)"
        @click="page++"
      >
        下一页
      </el-button>
    </div>
    <!-- 抽屉固定在一级工作区，队列刷新或被接管移除时也不会卸载当前回复框。 -->
    <el-drawer
      v-model="drawer"
      title="人工客服回复"
      size="min(680px, 100vw)"
      destroy-on-close
    >
      <template v-if="opened">
        <HandoffControls
          :key="opened"
          :conversation-id="opened"
        />
        <p v-if="messages.isLoading.value">
          正在加载对话……
        </p>
        <el-alert
          v-if="messages.isError.value"
          title="消息加载失败，请稍后重试"
          type="error"
        />
        <article
          v-for="message in newestMessages"
          :key="message.id"
          class="customer-message"
        >
          <small>{{ message.role === 'customer' ? '客户' : message.role === 'staff' ? '人工客服' : '智能客服' }}</small><p>{{ message.content }}</p>
        </article>
      </template>
    </el-drawer>
  </section>
</template>

<style scoped>
.handoff-inbox { margin: 24px 0 32px; padding: 24px; border: 1px solid #d9c998; border-radius: 16px; background: #fffcf3; }
.inbox-header, .inbox-tabs, .handoff-card, .handoff-card-title { display: flex; align-items: center; gap: 12px; }
.inbox-header, .handoff-card { justify-content: space-between; }
.inbox-header h2 { margin: 6px 0; font-size: 24px; }
.inbox-header p, .inbox-empty { color: #66736d; font-size: 14px; line-height: 1.8; }
.inbox-eyebrow { color: #856321; font-size: 13px; font-weight: 600; }
.inbox-tabs { flex-wrap: wrap; margin: 18px 0; font-size: 13px; color: #66736d; }
.handoff-card { margin-top: 12px; padding: 20px; background: white; border: 1px solid #e6dfc9; border-radius: 12px; }
.handoff-card-content { min-width: 0; overflow-wrap: anywhere; }
.handoff-card-title { flex-wrap: wrap; }
.handoff-card-title strong { font-size: 18px; }
.handoff-card p { white-space: pre-wrap; line-height: 1.7; }
.handoff-card small { color: #748078; }
.handoff-card > .el-button { flex-shrink: 0; min-height: 44px; }
@media (max-width: 650px) {
  .handoff-inbox { padding: 16px; }
  .inbox-header, .handoff-card { align-items: stretch; flex-direction: column; }
  .handoff-card > .el-button { width: 100%; }
}
</style>
