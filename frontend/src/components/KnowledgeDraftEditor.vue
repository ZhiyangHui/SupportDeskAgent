<script setup lang="ts">
// 草稿编辑留在组件内，服务器版本由 TanStack Query 管理；保存成功才刷新正式数据。
import { ref, watch } from "vue";
import { useMutation } from "@tanstack/vue-query";
import { ElMessageBox } from "element-plus";
import { isAxiosError } from "axios";
import { changeKnowledge, prepareKnowledge, saveKnowledgeDraft, type KnowledgeDetail } from "@/services/knowledge-service";

const props = defineProps<{ document: KnowledgeDetail }>();
const emit = defineEmits<{ saved: []; dirty: [value: boolean] }>();
const chunks = ref<KnowledgeDetail["draft_chunks"]>([]);
const dirty = ref(false);
const splitAt = ref<Record<number, number>>({});
const notice = ref("");
watch(() => [props.document.id, props.document.draft_revision], () => {
  chunks.value = props.document.draft_chunks.map(chunk => ({ ...chunk }));
  dirty.value = false;
  splitAt.value = {};
}, { immediate: true });
watch(dirty, value => emit("dirty", value));
const operation = useMutation({
  mutationFn: async (action: "prepare" | "save" | "publish") => {
    const { id, draft_revision: revision } = props.document;
    if (action === "prepare") await prepareKnowledge(id, revision);
    else if (action === "save") await saveKnowledgeDraft(id, revision, chunks.value);
    else await changeKnowledge(id, "publish", revision);
  },
  onSuccess: (_, action) => { notice.value = action === "publish" ? "发布成功，客服已使用此版本。" : "草稿已保存，尚未改变线上索引。"; emit("saved"); },
});
async function prepare() {
  if (chunks.value.length || dirty.value) {
    try { await ElMessageBox.confirm("重新生成会覆盖待发布草稿，但不会影响已发布索引。是否继续？", "重新生成分块", { type: "warning" }); }
    catch { return; }
  }
  operation.mutate("prepare");
}
function split(index: number) {
  const chunk = chunks.value[index];
  const at = splitAt.value[index];
  if (!chunk || !at) return;
  // 按 Unicode 字符而不是 UTF-16 码元拆分，避免把 emoji 等字符从中间截断。
  const chars = Array.from(chunk.content);
  const left = chars.slice(0, at).join("").trim();
  const right = chars.slice(at).join("").trim();
  if (!left || !right) { notice.value = "拆分位置必须使左右两侧都有正文。"; return; }
  chunks.value.splice(index, 1, { ...chunk, content: left }, { ...chunk, content: right });
  dirty.value = true;
  splitAt.value = {};
}
function merge(index: number) {
  const current = chunks.value[index];
  const next = chunks.value[index + 1];
  if (!current || !next || current.heading_path !== next.heading_path) return;
  // 只合并同章节相邻片段；不静默删除重叠文本，由员工查看确认。
  chunks.value.splice(index, 2, { ...current, content: current.content + "\n\n" + next.content });
  dirty.value = true;
  splitAt.value = {};
}
function errorText(error: unknown) {
  const detail = isAxiosError(error) ? error.response?.data?.detail : null;
  return typeof detail === "string" ? detail : "操作失败，请检查片段是否为空或超过 2000 字符；版本冲突时请重新加载。";
}
</script>

<template>
  <section>
    <p>草稿版本 {{ document.draft_revision }} · 已发布版本 {{ document.published_revision }}。预览和保存不调用向量服务；确认发布才会替换线上索引。</p>
    <p>按标题分组，完整章节最多保留 800 字符；更长章节按约 500 字符细分。同主题内可能有重叠，请检查规则和例外是否完整。</p>
    <el-alert
      v-for="warning in document.draft_warnings"
      :key="warning"
      :title="warning"
      type="warning"
      :closable="false"
    />
    <el-alert
      v-if="operation.isError.value"
      :title="errorText(operation.error.value)"
      type="error"
    />
    <p role="status">
      {{ notice }}
    </p>
    <div class="draft-actions">
      <el-button
        :disabled="operation.isPending.value"
        @click="prepare"
      >
        {{ chunks.length ? '重新生成草稿' : '生成分块预览' }}
      </el-button>
      <el-button
        :disabled="!dirty || operation.isPending.value || !chunks.length"
        @click="operation.mutate('save')"
      >
        保存分块调整
      </el-button>
      <el-button
        type="primary"
        :disabled="dirty || !chunks.length || operation.isPending.value"
        :loading="operation.isPending.value"
        @click="operation.mutate('publish')"
      >
        确认分块并发布
      </el-button>
    </div>
    <p v-if="dirty">
      有未保存的调整，请先保存，再确认发布。
    </p>
    <article
      v-for="(chunk, index) in chunks"
      :key="index"
      class="draft-chunk"
    >
      <strong>待发布片段 {{ index + 1 }} · {{ Array.from(chunk.content).length }} 字符</strong>
      <label>所属章节<el-input
        v-model="chunk.heading_path"
        :maxlength="1500"
        :disabled="operation.isPending.value"
        @input="dirty = true"
      /></label>
      <label>正文<el-input
        v-model="chunk.content"
        type="textarea"
        :rows="6"
        :maxlength="2000"
        :disabled="operation.isPending.value"
        @input="dirty = true"
      /></label>
      <div class="draft-actions">
        <label>在第几个字符后拆分 <el-input-number
          v-model="splitAt[index]"
          :min="1"
          :max="Math.max(1, Array.from(chunk.content).length - 1)"
          :disabled="operation.isPending.value"
        /></label>
        <el-button
          :disabled="!splitAt[index] || operation.isPending.value || chunks.length >= 300"
          @click="split(index)"
        >
          拆分
        </el-button>
        <el-button
          :disabled="!chunks[index + 1] || chunks[index + 1]?.heading_path !== chunk.heading_path || operation.isPending.value || (chunk.content.length + (chunks[index + 1]?.content.length ?? 0) + 2 > 2000)"
          @click="merge(index)"
        >
          与下一同章节片段合并
        </el-button>
      </div>
    </article>
  </section>
</template>

<style scoped>
.draft-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin: 16px 0; }
.draft-chunk { background: #f2f7f4; padding: 16px; border-radius: 12px; margin: 16px 0; }
.draft-chunk > label { display: block; margin-top: 12px; }
</style>
