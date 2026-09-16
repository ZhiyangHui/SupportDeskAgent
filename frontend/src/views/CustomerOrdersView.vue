<script setup lang="ts">
// 页面只维护表单与分页；服务端订单交给 Query 缓存，企业归属从路由取得并由后端再次验证。
import { computed, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { listOrders, createOrder, orderFormSchema, type OrderForm } from "@/services/order-service";
import { getCompany } from "@/services/customer-service";
import type { FormInstance } from "element-plus";

const companyId = String(useRoute().params.companyId);
const page = ref(1);
const cache = useQueryClient();
const company = useQuery({ queryKey: ["company", companyId], queryFn: () => getCompany(companyId), retry: false });
const orders = useQuery({ queryKey: computed(() => ["my-orders", companyId, page.value]), queryFn: () => listOrders(companyId, page.value), retry: false });
const form = reactive<OrderForm>({ product_name: "", amount: 99, status: "paid" });
const formRef = ref<FormInstance>();
const validationMessage = ref("");
const labels = { paid: "已支付（模拟）", shipped: "已发货", completed: "已完成" };
let attempt: { fingerprint: string; id: string } | null = null;
const creation = useMutation({ mutationFn: (data: OrderForm) => {
  // 当前页面重发相同表单复用请求键，防止响应丢失后重复创建。
  const fingerprint = JSON.stringify(data);
  if (attempt?.fingerprint !== fingerprint) attempt = { fingerprint, id: crypto.randomUUID() };
  return createOrder(companyId, data, attempt.id);
}, retry: false,
  async onSuccess() { attempt = null; form.product_name = ""; page.value = 1; await cache.invalidateQueries({ queryKey: ["my-orders", companyId] }); },
});
async function submit() {
  if (creation.isPending.value || !(await formRef.value?.validate().catch(() => false))) return;
  const result = orderFormSchema.safeParse(form);
  validationMessage.value = result.success ? "" : (result.error.issues[0]?.message ?? "请检查输入");
  if (result.success) creation.mutate(result.data);
}
</script>

<template>
  <main class="portal-panel">
    <h1>{{ company.data.value?.name ?? '当前企业' }} · 我的模拟订单</h1>
    <p>每个客户在每家企业下默认有三个订单。所有数据仅用于演示，不发生真实交易或退款。</p>
    <RouterLink
      class="portal-action-link"
      :to="`/customer/companies/${companyId}/chat`"
    >
      向 Agent 咨询订单或申请工单 →
    </RouterLink>
    <!-- 自建订单仅需商品、金额和模拟状态，不收集真实支付信息。 -->
    <el-form
      ref="formRef"
      novalidate
      :model="form"
      label-position="top"
      @submit.prevent="submit"
    >
      <!-- 统一由 Element Plus 和 Zod 校验，避免浏览器对小数金额的默认 step 规则阻止提交。 -->
      <el-form-item
        label="商品名称"
        prop="product_name"
        :rules="[{ required: true, whitespace: true, message: '请输入商品名称', trigger: 'blur' }]"
      >
        <el-input
          v-model="form.product_name"
          maxlength="100"
          placeholder="例如：家用机械设备"
        />
      </el-form-item>
      <el-form-item label="模拟金额（元）">
        <el-input-number
          v-model="form.amount"
          :min="0.01"
          :max="99999999"
          :precision="2"
        />
      </el-form-item>
      <el-form-item label="订单状态">
        <el-select v-model="form.status">
          <el-option
            v-for="(label, value) in labels"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
      </el-form-item>
      <el-button
        native-type="submit"
        type="primary"
        :loading="creation.isPending.value"
      >
        创建模拟订单
      </el-button>
    </el-form>
    <el-alert
      v-if="validationMessage"
      :title="validationMessage"
      type="warning"
      :closable="false"
    />
    <el-alert
      v-if="creation.isError.value"
      title="创建结果暂时无法确认，请先刷新订单列表核对，避免重复提交。"
      type="error"
      :closable="false"
    />
    <p v-if="orders.isPending.value">
      正在初始化并读取订单……
    </p>
    <div v-else-if="orders.isError.value">
      <p>订单加载失败，请确认企业和登录状态。</p><el-button @click="orders.refetch()">
        重试
      </el-button>
    </div>
    <el-empty
      v-else-if="!orders.data.value?.items.length"
      description="暂无订单"
    />
    <!-- 完整编号可以复制给 Agent；编号、商品信息和工单关联以数据库为准。 -->
    <article
      v-for="order in orders.data.value?.items ?? []"
      :key="order.id"
      class="customer-ticket"
    >
      <h2>{{ order.product_name }}</h2><p>订单号：{{ order.code }}</p>
      <p>¥{{ order.amount }} · {{ labels[order.status] }}</p>
      <RouterLink
        class="portal-action-link"
        :to="{ path: `/customer/companies/${companyId}/chat`, query: { orderCode: order.code } }"
      >
        咨询此订单 →
      </RouterLink>
    </article>
    <div class="portal-actions">
      <el-button
        :disabled="page === 1"
        @click="page--"
      >
        上一页
      </el-button><span>共 {{ orders.data.value?.total ?? 0 }} 单 · 第 {{ page }} 页</span><el-button
        :disabled="page * 20 >= (orders.data.value?.total ?? 0)"
        @click="page++"
      >
        下一页
      </el-button><el-button @click="orders.refetch()">
        刷新订单
      </el-button>
    </div>
  </main>
</template>
