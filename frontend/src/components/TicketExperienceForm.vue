<script setup lang="ts">
// 员工从已解决工单提炼可公开经验；不调用模型生成未经核实的故障原因。
import { computed, reactive, ref, watch } from "vue";
import { useMutation, useQuery } from "@tanstack/vue-query";
import { ElMessageBox } from "element-plus";
import { isAxiosError } from "axios";
import { createTicketExperience, getExperienceTicket, listExperienceTickets, type TicketExperienceInput } from "@/services/knowledge-service";

const emit = defineEmits<{ created: [id: string] }>();
const props = defineProps<{ ticketCode?: string }>();
const form = reactive<TicketExperienceInput>({ ticket_code: "", title: "", symptom: "", cause: "", solution: "", applicability: "" });
const selectedCode = ref(props.ticketCode ?? "");
const loadedCode = ref("");
const keywordInput = ref("");
const keyword = ref("");
const page = ref(1);
const candidates = useQuery({ queryKey: ["experience-tickets", keyword, page], queryFn: () => listExperienceTickets(keyword.value, page.value) });
// 与选择编号绑定，慢请求返回时也不会将 A 工单内容填入 B 工单草稿。
const source = useQuery({ queryKey: ["experience-source", selectedCode], queryFn: () => getExperienceTicket(selectedCode.value),
  enabled: computed(() => !!selectedCode.value), refetchOnWindowFocus: false });
// 返回页面时查询可能已经命中缓存，因此初始化也要执行，不能只等接口数据变化。
// 同一工单仅预填一次，后台重新获取数据时保留员工正在编辑的内容。
watch(() => source.data.value, data => {
  if (!data || data.code !== selectedCode.value || loadedCode.value === data.code) return;
  Object.assign(form, { ticket_code: data.code, title: data.title.slice(0, 160),
    symptom: data.description.slice(0, 1500), cause: "未确认", solution: "", applicability: "" });
  loadedCode.value = data.code;
}, { immediate: true });
async function selectTicket(code: string) {
  if (code === selectedCode.value) return;
  if (loadedCode.value) {
    try { await ElMessageBox.confirm("切换工单将清空当前经验表单，是否继续？", "切换工单"); }
    catch { return; }
  }
  loadedCode.value = "";
  Object.assign(form, { ticket_code: "", title: "", symptom: "", cause: "", solution: "", applicability: "" });
  selectedCode.value = code;
}
const fields = [
  { key: "symptom", label: "问题现象", placeholder: "例如：无线键盘间歇断连，不填写客户姓名或账号" },
  { key: "cause", label: "原因", placeholder: "填写已核实原因；不能确认时请写“未确认”，不要猜测" },
  { key: "solution", label: "实际解决办法", placeholder: "填写该工单实际采用并验证的处理步骤" },
  { key: "applicability", label: "适用范围与限制", placeholder: "例如：仅适用于接收器接触不良，不适用于进水或硬件损坏" },
] as const;
const ready = computed(() => loadedCode.value === selectedCode.value && !source.isError.value && Object.values(form).every(value => value.trim()));
const save = useMutation({ mutationFn: () => createTicketExperience({ ...form }), onSuccess: result => {
  Object.assign(form, { ticket_code: "", title: "", symptom: "", cause: "", solution: "", applicability: "" });
  emit("created", result.id);
} });
const error = computed(() => {
  const detail = isAxiosError(save.error.value) ? save.error.value.response?.data?.detail : null;
  return typeof detail === "string" ? detail : "保存失败，请检查输入内容后重试。";
});
</script>

<template>
  <section>
    <p>支持已解决或已关闭工单。关闭不代表问题已解决，请如实填写实际结果，不把取消、重复关闭等情况当成成功经验。</p>
    <el-alert
      title="选择工单后自动读取脱敏标题和问题描述。客户诉求仅供参考，不等于解决结果；内部备注不自动入库。系统无法识别全部隐私，发布前仍须逐项审核。"
      type="warning"
      :closable="false"
    />
    <form
      class="experience-form"
      @submit.prevent="save.mutate()"
    >
      <div class="ticket-search">
        <el-input
          v-model="keywordInput"
          placeholder="按工单编号或标题搜索"
          :maxlength="100"
          @keydown.enter.prevent="keyword = keywordInput.trim(); page = 1"
        />
        <el-button @click="keyword = keywordInput.trim(); page = 1">
          查询工单
        </el-button>
      </div>
      <!-- 候选直接展示，避免必须展开下拉框才知道数据库里有哪些可用工单。 -->
      <section aria-label="可整理经验的工单">
        <div class="ticket-search">
          <strong>已解决／已关闭工单</strong>
          <el-button
            :loading="candidates.isFetching.value"
            @click="candidates.refetch()"
          >
            刷新列表
          </el-button>
        </div>
        <article
          v-for="ticket in candidates.data.value ?? []"
          :key="ticket.code"
          class="experience-ticket"
          :class="{ 'is-selected': selectedCode === ticket.code }"
        >
          <div class="experience-ticket-text">
            <strong>{{ ticket.title }}</strong>
            <small>{{ ticket.code }} · {{ ticket.status === 'closed' ? '已关闭' : '已解决' }}</small>
          </div>
          <el-button
            type="primary"
            plain
            :aria-label="`读取工单 ${ticket.code}`"
            :disabled="save.isPending.value || selectedCode === ticket.code"
            @click="selectTicket(ticket.code)"
          >
            {{ selectedCode === ticket.code ? '已选择' : '读取内容' }}
          </el-button>
        </article>
      </section>
      <div class="ticket-search">
        <el-button
          :disabled="page === 1 || candidates.isFetching.value"
          @click="page--"
        >
          上一页工单
        </el-button>
        <span>第 {{ page }} 页</span>
        <el-button
          :disabled="(candidates.data.value?.length ?? 0) < 20 || candidates.isFetching.value"
          @click="page++"
        >
          下一页工单
        </el-button>
      </div>
      <el-alert
        v-if="candidates.isError.value"
        title="工单列表加载失败，请重试。"
        type="error"
      />
      <el-button
        v-if="candidates.isError.value"
        @click="candidates.refetch()"
      >
        重新加载工单列表
      </el-button>
      <p v-if="candidates.isSuccess.value && !candidates.data.value?.length">
        没有匹配的已解决或已关闭工单。
      </p>
      <el-alert
        v-else-if="candidates.isSuccess.value && !selectedCode"
        title="请点击工单旁的“读取内容”，系统会自动填入标题和问题现象。"
        type="info"
        :closable="false"
      />
      <p
        v-if="source.isFetching.value"
        role="status"
      >
        正在读取工单内容……
      </p>
      <el-alert
        v-if="source.isError.value"
        title="工单读取失败，可能已变更状态或不属于本企业。请重新选择或重试。"
        type="error"
      />
      <el-button
        v-if="source.isError.value"
        @click="source.refetch()"
      >
        重新读取工单
      </el-button>
      <template v-if="source.data.value && loadedCode === selectedCode">
        <p>已从数据库读取 {{ loadedCode }}。原因默认“未确认”，请补充实际处理结果。</p>
        <el-collapse>
          <el-collapse-item
            title="查看脱敏工单素材（仅供整理参考）"
            name="source"
          >
            <p class="source-text">
              问题描述：{{ source.data.value.description }}
            </p>
            <p class="source-text">
              客户诉求（非解决结果）：{{ source.data.value.desired_resolution || '未填写' }}
            </p>
            <p class="source-text">
              影响情况：{{ source.data.value.impact_note || '未填写' }}
            </p>
          </el-collapse-item>
        </el-collapse>
        <el-alert
          v-if="source.data.value.description.length > 1500"
          title="原描述较长，表单仅预填前 1500 字符，请展开完整素材核对并提炼。"
          type="warning"
        />
      </template>
      <label>经验标题<el-input
        v-model="form.title"
        placeholder="例如：无线键盘间歇断连的处理经验"
        :maxlength="160"
        :disabled="save.isPending.value"
      /></label>
      <label
        v-for="field in fields"
        :key="field.key"
      >{{ field.label }}<el-input
        v-model="form[field.key]"
        type="textarea"
        :rows="3"
        :maxlength="1500"
        :placeholder="field.placeholder"
        :disabled="save.isPending.value"
      /></label>
      <el-alert
        v-if="save.isError.value"
        :title="error"
        type="error"
      />
      <el-button
        native-type="submit"
        type="primary"
        :disabled="!ready"
        :loading="save.isPending.value"
      >
        保存经验草稿并审核
      </el-button>
    </form>
  </section>
</template>

<style scoped>
.experience-form { display: grid; gap: 16px; margin: 16px 0; }
.experience-form label { display: grid; gap: 8px; }
.experience-form .el-button { justify-self: start; }
.ticket-search { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.source-text { white-space: pre-wrap; overflow-wrap: anywhere; }
.experience-ticket { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px; margin-top: 10px; border: 1px solid #dce5e1; border-radius: 10px; }
.experience-ticket.is-selected { border-color: #26745e; background: #f0f7f3; }
.experience-ticket-text { display: grid; gap: 6px; min-width: 0; overflow-wrap: anywhere; }
.experience-ticket-text small { color: #61736b; }
@media (max-width: 480px) { .experience-ticket { align-items: flex-start; flex-direction: column; } }
</style>
