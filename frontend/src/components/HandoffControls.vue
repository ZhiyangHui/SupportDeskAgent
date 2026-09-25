<script setup lang="ts">
// 独立接管面板负责网络写操作，消息列表仍由父页面的 Query 缓存管理。
import { computed, ref, watch } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { isAxiosError } from "axios";
import { changeHandoff, getHandoff, sendStaffReply } from "@/services/handoff-service";
import { checkStaffSession } from "@/services/access-service";

const props = defineProps<{ conversationId: string }>();
const cache = useQueryClient();
const identity = useQuery({ queryKey: ["staff-identity"], queryFn: checkStaffSession, retry: false });
const draft = ref("");
const sentSuccessfully = ref(false);
const refreshFailed = ref(false);
watch(draft, (value) => { if (value.trim()) sentSuccessfully.value = false; });
// 相同内容重试复用请求标识；切换会话由父组件 key 重建，防止串发到另一客户。
let pending: { content: string; key: string } | null = null;
const state = useQuery({
  queryKey: computed(() => ["staff-handoff", props.conversationId]),
  queryFn: () => getHandoff(props.conversationId, "staff"),
  refetchInterval: 3000,
});
const mine = computed(() => state.data.value?.handoff_staff_id === identity.data.value?.id && !!identity.data.value);
const occupied = computed(() => !!state.data.value?.handoff_staff_id && !mine.value);
const mutation = useMutation({
  onMutate: () => { sentSuccessfully.value = false; refreshFailed.value = false; },
  mutationFn: async (action: "takeover" | "resume" | "reply") => {
    if (action !== "reply") return changeHandoff(props.conversationId, action);
    const content = draft.value.trim();
    if (!content) return;
    if (pending?.content !== content) pending = { content, key: crypto.randomUUID() };
    await sendStaffReply(props.conversationId, content, pending.key);
    if (draft.value.trim() === content) draft.value = "";
    pending = null;
  },
  onSuccess: (result, action) => {
    sentSuccessfully.value = action === "reply";
    // 接管状态使用写接口的确定结果立即更新，不等待下一次轮询。
    if (result) cache.setQueryData(["staff-handoff", props.conversationId], result);
  },
  onSettled: () => {
    // 发送完成与后台同步分开：返回 Promise 会让 mutation 一直停在 pending。
    // 刷新失败只能提示同步问题，不能把已成功发送的消息当作发送失败。
    void Promise.all([state.refetch(), cache.invalidateQueries({ queryKey: ["staff-conversation", props.conversationId] }), cache.invalidateQueries({ queryKey: ["handoff-queue"] })])
      .catch(() => { refreshFailed.value = true; });
  },
});
const errorText = computed(() => {
  const error = mutation.error.value ?? state.error.value;
  if (!error) return "";
  const detail = isAxiosError(error) ? error.response?.data?.detail : null;
  return typeof detail === "string" ? detail : "操作失败，请稍后重试；相同内容重试不会重复发送。";
});
</script>

<template>
  <section
    class="handoff-controls"
    aria-label="人工接管控制"
  >
    <p>{{ state.data.value?.status === 'handed_off' ? '人工接管中 · AI 暂停回复' : '智能客服服务中' }}</p>
    <p v-if="occupied">
      该会话已由其他客服接管，您可以查看消息，但不能回复或恢复 AI。
    </p>
    <el-alert
      v-if="errorText"
      :title="errorText"
      type="error"
      :closable="false"
    />
    <div class="portal-actions">
      <el-button
        type="primary"
        :disabled="!state.data.value || !identity.data.value || occupied || mine || mutation.isPending.value || state.data.value.status === 'closed'"
        @click="mutation.mutate('takeover')"
      >
        接管会话
      </el-button>
      <el-button
        :disabled="!mine || state.data.value?.status !== 'handed_off' || mutation.isPending.value"
        @click="mutation.mutate('resume')"
      >
        恢复智能客服
      </el-button>
    </div>
    <template v-if="state.data.value?.status === 'handed_off' && mine">
      <el-input
        v-model="draft"
        type="textarea"
        :rows="3"
        :maxlength="4000"
        placeholder="输入人工回复"
        :disabled="mutation.isPending.value"
      />
      <el-button
        type="primary"
        :loading="mutation.isPending.value && mutation.variables.value === 'reply'"
        :disabled="!draft.trim() || mutation.isPending.value"
        @click="mutation.mutate('reply')"
      >
        {{ mutation.isPending.value && mutation.variables.value === 'reply' ? '发送中…' : '发送人工回复' }}
      </el-button>
      <p
        v-if="sentSuccessfully"
        class="send-success"
        role="status"
      >
        回复已发送。输入新内容即可继续回复。
      </p>
      <p
        v-else-if="!draft.trim() && !mutation.isPending.value"
        class="send-hint"
      >
        请输入回复内容后发送。
      </p>
      <p
        v-if="refreshFailed"
        role="status"
      >
        消息列表同步暂时失败，请稍后刷新；无需重复发送已成功的回复。
      </p>
    </template>
  </section>
</template>

<style scoped>
.handoff-controls { padding: 16px; margin: 16px 0; border: 1px solid #d4e3db; border-radius: 12px; background: #f5f9f7; }
.handoff-controls > .el-button { margin-top: 12px; }
.send-success { color: #17634d; font-size: 14px; }
.send-hint { color: #748078; font-size: 13px; }
</style>
