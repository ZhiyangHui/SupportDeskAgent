<script setup lang="ts">
// 文档状态交给 TanStack Query，编辑草稿留在当前页面；不把向量或 API 密钥交给浏览器。
import { computed, ref } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { isAxiosError } from "axios";
import StaffNavigation from "@/components/StaffNavigation.vue";
import KnowledgeDraftEditor from "@/components/KnowledgeDraftEditor.vue";
import { ElMessageBox } from "element-plus";
import { changeKnowledge, createKnowledge, getKnowledge, listKnowledge, searchKnowledge, uploadKnowledge } from "@/services/knowledge-service";

const title = ref("");
const content = ref("");
const query = ref("");
const page = ref(1);
const cache = useQueryClient();
const documents = useQuery({ queryKey: ["knowledge", page], queryFn: () => listKnowledge(page.value) });
// 按文档 ID 隔离详情缓存，快速切换文档时不会把上一份原文显示在新标题下。
const selectedId = ref("");
const detailOpen = ref(false);
const detailTab = ref("chunks");
const draftDirty = ref(false);
async function closeDetail(done: () => void) {
  if (draftDirty.value) {
    try { await ElMessageBox.confirm("分块调整尚未保存，确定关闭并放弃调整吗？", "未保存的调整"); }
    catch { return; }
  }
  draftDirty.value = false;
  done();
}
const detail = useQuery({ queryKey: ["knowledge", "detail", selectedId],
  queryFn: () => getKnowledge(selectedId.value), enabled: computed(() => detailOpen.value && !!selectedId.value),
});
function openDetail(id: string, tab: string) {
  selectedId.value = id;
  detailTab.value = tab;
  detailOpen.value = true;
}
function errorText(error: unknown): string {
  const detail = isAxiosError(error) ? error.response?.data?.detail : null;
  return typeof detail === "string" ? detail : "操作失败，请检查输入或稍后重试。";
}
const save = useMutation({ mutationFn: () => createKnowledge(title.value, content.value), onSuccess: () => {
  title.value = ""; content.value = ""; void cache.invalidateQueries({ queryKey: ["knowledge"] });
} });
const upload = useMutation({ mutationFn: uploadKnowledge, onSuccess: () => { void cache.invalidateQueries({ queryKey: ["knowledge"] }); } });
function selectFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) upload.mutate(file);
  input.value = "";
}
const change = useMutation({ mutationFn: ({ id, action }: { id: string; action: "publish" | "disable" }) => changeKnowledge(id, action),
  onSuccess: () => { void cache.invalidateQueries({ queryKey: ["knowledge"] }); } });
const search = useMutation({ mutationFn: () => searchKnowledge(query.value) });
</script>

<template>
  <main class="app-shell">
    <StaffNavigation />
    <section class="workspace ticket-workspace">
      <div class="portal-panel knowledge-panel">
        <h1>企业知识库</h1>
        <el-alert
          title="仅发布允许客户阅读的资料。建立索引会将文本发送至配置的 Embedding 供应商；客服回答时相关片段也会发送至聊天模型。请勿上传密码、密钥或内部保密资料。"
          type="warning"
          :closable="false"
        />
        <h2>录入文档草稿</h2>
        <el-input
          v-model="title"
          placeholder="文档标题，例如：售后服务政策"
          :maxlength="200"
        />
        <el-input
          v-model="content"
          type="textarea"
          :rows="7"
          :maxlength="60000"
          placeholder="粘贴正文，最多 60000 字符"
        />
        <el-button
          type="primary"
          :disabled="!title.trim() || !content.trim()"
          :loading="save.isPending.value"
          @click="save.mutate()"
        >
          保存草稿
        </el-button>
        <label class="file-upload">或上传 UTF-8 TXT / Markdown（最大 240 KB）：<input
          type="file"
          accept=".txt,.md"
          :disabled="upload.isPending.value"
          @change="selectFile"
        ></label>
        <el-alert
          v-if="save.isError.value || upload.isError.value"
          :title="errorText(save.error.value ?? upload.error.value)"
          type="error"
        />
        <h2>本企业文档</h2>
        <p>按章节生成分块，预览并调整后再发布。旧索引保持可用，直到新版本发布成功。</p>
        <p v-if="documents.isLoading.value">
          正在加载……
        </p>
        <el-alert
          v-if="documents.isError.value"
          title="文档加载失败"
          type="error"
        />
        <el-alert
          v-if="change.isError.value"
          :title="errorText(change.error.value)"
          type="error"
        />
        <p v-if="documents.data.value?.length === 0">
          暂无文档，请先保存草稿。
        </p>
        <article
          v-for="doc in documents.data.value ?? []"
          :key="doc.id"
          class="knowledge-document"
        >
          <div><strong>{{ doc.title }}</strong><p>{{ doc.published ? '已发布' : doc.chunk_count ? '已停用' : '草稿' }} · {{ doc.chunk_count }} 个切片</p></div>
          <el-button @click="openDetail(doc.id, 'source')">
            查看原文
          </el-button>
          <el-button @click="openDetail(doc.id, 'chunks')">
            查看分块（{{ doc.chunk_count }}）
          </el-button>
          <el-button
            type="primary"
            :disabled="change.isPending.value"
            @click="openDetail(doc.id, 'draft')"
          >
            预览与发布
          </el-button>
          <el-button
            v-if="doc.published"
            :disabled="change.isPending.value"
            @click="change.mutate({ id: doc.id, action: 'disable' })"
          >
            停用
          </el-button>
        </article>
        <p
          v-if="change.isPending.value"
          role="status"
        >
          正在处理索引，请勿重复提交……
        </p>
        <div class="portal-actions">
          <el-button
            :disabled="page === 1"
            @click="page--"
          >
            上一页
          </el-button><span>第 {{ page }} 页</span><el-button
            :disabled="(documents.data.value?.length ?? 0) < 20"
            @click="page++"
          >
            下一页
          </el-button>
        </div>
        <h2>检索测试</h2>
        <p>只检索本企业已发布且与当前向量模型匹配的资料。相似度不代表回答正确率。</p>
        <el-input
          v-model="query"
          :maxlength="500"
          placeholder="例如：退货需要满足什么条件？"
        />
        <el-button
          :loading="search.isPending.value"
          :disabled="!query.trim()"
          @click="search.mutate()"
        >
          测试检索
        </el-button>
        <el-alert
          v-if="search.isError.value"
          :title="errorText(search.error.value)"
          type="error"
        />
        <p v-if="search.isSuccess.value && !search.data.value?.length">
          没有符合阈值的已发布资料，请检查文档、模型配置及问题。
        </p>
        <article
          v-for="hit in search.data.value ?? []"
          :key="hit.chunk_id"
          class="knowledge-hit"
        >
          <strong>{{ hit.title }} · 片段 {{ hit.position }}</strong><small>相似度 {{ hit.score }}</small><p>{{ hit.content }}</p>
        </article>
      </div>
      <!-- 原文仅作纯文本展示，不执行上传文档中的 HTML，避免资料变成可执行内容。 -->
      <el-dialog
        v-model="detailOpen"
        title="知识文档详情"
        width="min(900px, 94vw)"
        :before-close="closeDetail"
        destroy-on-close
      >
        <p
          v-if="detail.isLoading.value"
          role="status"
        >
          正在加载文档……
        </p>
        <el-alert
          v-if="detail.isError.value"
          :title="errorText(detail.error.value)"
          type="error"
        />
        <el-button
          v-if="detail.isError.value"
          @click="detail.refetch()"
        >
          重新加载
        </el-button>
        <template v-if="detail.data.value">
          <h3>{{ detail.data.value.title }}</h3>
          <el-tabs v-model="detailTab">
            <el-tab-pane
              label="待发布分块"
              name="draft"
            >
              <KnowledgeDraftEditor
                :key="selectedId"
                :document="detail.data.value"
                @dirty="draftDirty = $event"
                @saved="cache.invalidateQueries({ queryKey: ['knowledge'] })"
              />
            </el-tab-pane>
            <el-tab-pane
              label="原文"
              name="source"
            >
              <pre class="knowledge-source">{{ detail.data.value.content }}</pre>
            </el-tab-pane>
            <el-tab-pane
              :label="`已入库分块（${detail.data.value.chunks.length}）`"
              name="chunks"
            >
              <p>按原文顺序展示实际保存的全部片段；边界内容可能因重叠而重复。</p>
              <el-empty
                v-if="!detail.data.value.chunks.length"
                description="尚未建立索引，请先发布文档。"
              />
              <article
                v-for="chunk in detail.data.value.chunks"
                :key="chunk.id"
                class="knowledge-hit"
              >
                <strong>片段 {{ chunk.position }}</strong>
                <p>{{ chunk.heading_path || '旧版片段：尚无章节路径' }}</p>
                <small>{{ Array.from(chunk.content).length }} 字符</small>
                <p>{{ chunk.content }}</p>
              </article>
            </el-tab-pane>
          </el-tabs>
        </template>
      </el-dialog>
    </section>
  </main>
</template>

<style scoped>
.knowledge-panel > .el-input, .knowledge-panel > .el-textarea { margin: 12px 0; }
.file-upload { display: block; margin: 20px 0; line-height: 2; }
.file-upload input { max-width: 100%; }
.knowledge-document { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; padding: 16px 0; border-bottom: 1px solid #dce5df; }
.knowledge-document > div { flex: 1; min-width: 160px; overflow-wrap: anywhere; }
.knowledge-hit { margin-top: 16px; padding: 16px; border-radius: 10px; background: #f2f7f4; }
.knowledge-hit small { display: block; margin-top: 8px; }
.knowledge-hit p { white-space: pre-wrap; overflow-wrap: anywhere; }
.knowledge-source { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.8; }
</style>
