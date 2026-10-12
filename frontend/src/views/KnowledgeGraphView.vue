<script setup lang="ts">
// 页面只是知识浏览器；知识内容由后端版本化发布，不依赖员工逐条输入或模型即时生成。
import { computed, ref, watch } from "vue";
import { useQuery } from "@tanstack/vue-query";
import StaffNavigation from "@/components/StaffNavigation.vue";
import { getDomainCatalog, graphError, kindLabels } from "@/services/knowledge-graph-service";

const catalog = useQuery({ queryKey: ["domain-knowledge"], queryFn: getDomainCatalog, retry: false });
const category = ref("");
const symptom = ref("");
const nodes = computed(() => new Map(catalog.data.value?.nodes.map(node => [node.id, node]) ?? []));
const categories = computed(() => catalog.data.value?.nodes.filter(node => node.kind === "category") ?? []);
const symptoms = computed(() => {
  const ids = new Set(catalog.data.value?.paths.filter(path => !category.value || path.category === category.value).map(path => path.symptom));
  return catalog.data.value?.nodes.filter(node => node.kind === "symptom" && ids.has(node.id)) ?? [];
});
const paths = computed(() => catalog.data.value?.paths.filter(path =>
  (!category.value || path.category === category.value) && (!symptom.value || path.symptom === symptom.value)) ?? []);
watch(category, () => { symptom.value = ""; });
// 新版本可能移除某类别；清理失效筛选，不把旧筛选导致的空列表误报为知识丢失。
watch(catalog.data, data => {
  if (category.value && !data?.nodes.some(node => node.id === category.value)) category.value = "";
  if (symptom.value && !data?.nodes.some(node => node.id === symptom.value)) symptom.value = "";
});
function concept(id: string) {
  return nodes.value.get(id) ?? { name: "知识引用异常", description: "请核对后端知识版本。" };
}
</script>

<template>
  <main class="app-shell">
    <StaffNavigation />
    <section class="workspace ticket-workspace">
      <div class="portal-panel domain-panel">
        <header class="domain-header">
          <div>
            <p class="eyebrow">
              长期解法 · 后端维护 · 只读浏览
            </p><h1>售后领域知识图谱</h1>
          </div>
          <el-button
            :loading="catalog.isFetching.value"
            @click="catalog.refetch()"
          >
            刷新知识状态
          </el-button>
        </header>
        <p class="intro">
          这里存储如何排查和处理一类问题，不存客户、订单、工单或文档副本。每条路径都保留自己的核实步骤、适用条件和未解决时的处理方式。
        </p>
        <p v-if="catalog.isPending.value">
          正在读取 Neo4j 中的领域知识……
        </p>
        <el-alert
          v-if="catalog.isError.value"
          :title="graphError(catalog.error.value)"
          type="error"
          :closable="false"
        />
        <!-- 读取失败时隐藏旧缓存，避免把上次成功结果冒充当前服务状态。 -->
        <template v-if="catalog.data.value && !catalog.isError.value">
          <div class="catalog-meta">
            <span>知识版本 v{{ catalog.data.value.version }}</span>
            <span>{{ catalog.data.value.nodes.length }} 个知识节点</span>
            <span>{{ catalog.data.value.paths.length }} 条完整路径</span>
          </div>
          <el-alert
            :title="catalog.data.value.maturity === 'demo' ? '当前为演示知识，不代表厂家诊断或企业售后承诺；尚未接入 Agent 自动回答。' : '知识已标记为核验版本；仍需核实客户实际情况，不自动认定原因或承诺权益。'"
            type="warning"
            :closable="false"
          />
          <details class="provenance">
            <summary>知识来源与适用边界</summary><p>{{ catalog.data.value.provenance }}</p>
          </details>
          <div
            class="ontology"
            aria-label="固定知识结构"
          >
            <span
              v-for="(label, kind) in kindLabels"
              :key="kind"
            >{{ label }}<small>{{ catalog.data.value.nodes.filter(node => node.kind === kind).length }} 个</small></span>
          </div>
          <div class="filters">
            <label>产品类别<select
              v-model="category"
              aria-label="产品类别"
            ><option value="">全部类别</option><option
              v-for="item in categories"
              :key="item.id"
              :value="item.id"
            >{{ item.name }}</option></select></label>
            <label>问题现象<select
              v-model="symptom"
              aria-label="问题现象"
            ><option value="">全部现象</option><option
              v-for="item in symptoms"
              :key="item.id"
              :value="item.id"
            >{{ item.name }}</option></select></label>
            <span>匹配 {{ paths.length }} 条排查路径</span>
          </div>
          <p
            v-if="paths.length === 0"
            class="empty"
          >
            暂无对应解法，请转人工核实，不根据相似名称猜测方案。
          </p>
          <article
            v-for="path in paths"
            :key="path.id"
            class="diagnostic-path"
          >
            <div class="path-heading">
              <h2>{{ concept(path.symptom).name }}</h2><span>{{ concept(path.category).name }}</span>
            </div>
            <div class="path-flow">
              <div><small>可能原因 · 尚待核实</small><strong>{{ concept(path.cause).name }}</strong><p>{{ concept(path.cause).description }}</p></div>
              <span
                class="arrow"
                aria-hidden="true"
              >→</span>
              <div><small>完成检查并核对条件后</small><strong>{{ concept(path.solution).name }}</strong><p>{{ concept(path.solution).description }}</p></div>
            </div>
            <p class="explanation">
              {{ path.explanation }}
            </p>
            <h3>按顺序核实</h3>
            <ol class="checks">
              <li
                v-for="id in path.checks"
                :key="id"
              >
                <strong>{{ concept(id).name }}</strong><p>{{ concept(id).description }}</p>
              </li>
            </ol>
            <div class="conditions">
              <section>
                <h3>必须满足 · 未知不等于满足</h3><ul>
                  <li
                    v-for="id in path.requires"
                    :key="id"
                  >
                    <strong>{{ concept(id).name }}</strong><p>{{ concept(id).description }}</p>
                  </li>
                </ul>
              </section>
              <section class="excluded">
                <h3>出现以下情况，不使用本方案</h3><ul>
                  <li
                    v-for="id in path.excludes"
                    :key="id"
                  >
                    <strong>{{ concept(id).name }}</strong><p>{{ concept(id).description }}</p>
                  </li><li v-if="!path.excludes.length">
                    未列举额外排除条件，仍需满足全部前提。
                  </li>
                </ul>
              </section>
            </div>
            <p class="escalation">
              <strong>未解决 / 无法确认：</strong>{{ path.escalation }}
            </p>
          </article>
        </template>
      </div>
    </section>
  </main>
</template>

<style scoped>
.domain-panel { max-width: none; }
.domain-header { display: flex; align-items: center; justify-content: space-between; gap: 20px; flex-wrap: wrap; }
.eyebrow { color: #4d7d66; font-size: 13px; letter-spacing: 1px; }
h1 { margin: 8px 0; }
.intro, .provenance p { color: #587163; line-height: 1.8; }
.catalog-meta { display: flex; flex-wrap: wrap; gap: 12px; margin: 22px 0; }
.catalog-meta span { padding: 8px 12px; background: #eff5f1; color: #38614d; border-radius: 8px; font-size: 13px; }
.provenance { padding: 14px 0; }
summary { color: #235e43; cursor: pointer; padding: 8px 0; }
.ontology { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; margin: 12px 0 26px; }
.ontology > span { padding: 16px 10px; border: 1px solid #d6e3db; border-radius: 10px; text-align: center; color: #284d39; }
.ontology small { display: block; margin-top: 8px; color: #718779; }
.filters { display: flex; gap: 20px; align-items: end; flex-wrap: wrap; padding: 18px; border-radius: 12px; background: #f5f8f6; }
.filters label { display: flex; flex-direction: column; gap: 10px; color: #496652; flex: 1; min-width: 140px; }
.filters select { min-height: 44px; border: 1px solid #becfc3; border-radius: 8px; padding: 10px; background: #fff; font: inherit; color: #284d39; }
.filters > span { color: #5c7264; font-size: 13px; padding-bottom: 12px; }
.diagnostic-path { margin-top: 24px; border: 1px solid #d4e1d8; border-radius: 16px; padding: 24px; }
.path-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 14px; margin-bottom: 18px; }
.path-heading h2 { margin: 0; font-size: 21px; }
.path-heading span { padding: 5px 10px; background: #edf5ef; color: #437154; border-radius: 6px; font-size: 13px; }
.path-flow { display: grid; grid-template-columns: 1fr auto 1fr; gap: 14px; align-items: center; }
.path-flow > div { height: 100%; box-sizing: border-box; border-radius: 12px; padding: 18px; background: #edf5f0; }
.path-flow small { display: block; color: #647f6d; margin-bottom: 10px; }
.path-flow strong { display: block; color: #24573b; font-size: 17px; }
.path-flow p, .checks p, .conditions p { color: #627567; font-size: 14px; line-height: 1.7; margin-bottom: 0; }
.arrow { color: #759882; font-size: 22px; }
h3 { font-size: 15px; margin-top: 22px; }
.explanation { color: #63766b; line-height: 1.8; font-size: 14px; }
.checks { padding-left: 24px; }.checks li { padding: 8px 0 8px 8px; }
.conditions { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 18px 0; }
.conditions section { padding: 0 16px 14px; border-radius: 10px; background: #f5f8f6; }
.conditions .excluded { background: #fff8ef; }
.conditions ul { padding-left: 20px; }.conditions li { margin-bottom: 12px; }
.escalation { padding: 16px; background: #f3f5f6; border-radius: 8px; color: #53636a; line-height: 1.8; font-size: 14px; }
@media (max-width: 1100px) { .ontology { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 600px) { .domain-panel { padding: 16px; } .path-flow, .conditions { grid-template-columns: 1fr; } .arrow { transform: rotate(90deg); text-align: center; } .diagnostic-path { padding: 16px; } }
</style>
