<script setup lang="ts">
// 客户与客服共用相同的业务字段和空值文案，内部备注、权限与操作按钮由各自页面负责。
defineProps<{
  description: string;
  desiredResolution: string;
  impactNote: string;
  order?: { code: string; product_name: string } | null;
}>();
</script>

<template>
  <!-- 关联订单来自后端只读摘要，与可修改的客户问题分区，避免把编号当成描述来改。 -->
  <section
    v-if="order"
    class="ticket-order-summary"
    aria-label="关联订单（只读）"
  >
    <h4>关联订单 <span>只读</span></h4>
    <p>{{ order.product_name }}</p>
    <p class="order-code">
      订单号：{{ order.code }}
    </p>
  </section>
  <dl
    class="ticket-issue-details"
    aria-label="工单问题信息"
  >
    <div><dt>问题描述</dt><dd>{{ description || '未填写具体问题' }}</dd></div>
    <div><dt>售后诉求</dt><dd>{{ desiredResolution || '未填写' }}</dd></div>
    <div><dt>影响／紧急情况说明</dt><dd>{{ impactNote || '未填写' }}</dd></div>
  </dl>
</template>

<style scoped>
.ticket-order-summary { padding: 14px 16px; margin-bottom: 20px; border-radius: 10px; background: #f3f7f5; border: 1px solid #dce7e1; overflow-wrap: anywhere; }
.ticket-order-summary h4 { margin: 0 0 8px; font-size: 14px; color: #344c40; }
.ticket-order-summary h4 span { margin-left: 8px; font-size: 12px; font-weight: normal; color: #748078; }
.ticket-order-summary p { margin: 4px 0 0; font-size: 14px; color: #283d33; }
.ticket-order-summary .order-code { font-size: 12px; color: #748078; }
.ticket-issue-details { display: grid; gap: 18px; margin: 0; }
.ticket-issue-details > div { display: grid; grid-template-columns: 140px minmax(0, 1fr); gap: 16px; align-items: start; }
dt { color: #748078; font-size: 13px; line-height: 1.8; }
dd { margin: 0; color: #283d33; font-size: 14px; line-height: 1.8; white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 600px) {
  .ticket-issue-details > div { grid-template-columns: minmax(0, 1fr); gap: 4px; }
}
</style>
