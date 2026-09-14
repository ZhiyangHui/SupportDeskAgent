<script setup lang="ts">
// 企业目录只负责选择服务对象；不会把所选企业写入员工认证上下文。
import { computed, ref, watch } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { listCompanies } from "@/services/customer-service";
const page = ref(1);
const keyword = ref("");
watch(keyword, () => { page.value = 1; });
const query = useQuery({ queryKey: computed(() => ["companies", page.value, keyword.value]), queryFn: () => listCompanies(page.value, keyword.value) });
</script>
<template>
  <main class="portal-panel">
    <h1>选择您要咨询的企业</h1><p>每家企业的会话独立保存。请核对企业名称与编号；列表不代表平台资质认证。</p>
    <el-input
      v-model="keyword"
      placeholder="搜索企业名称"
      clearable
      aria-label="搜索企业"
    />
    <p v-if="query.isLoading.value">
      正在加载企业……
    </p>
    <div v-else-if="query.isError.value">
      <p>企业加载失败</p><el-button @click="query.refetch()">
        重试
      </el-button>
    </div>
    <el-empty
      v-else-if="!query.data.value?.length"
      description="暂无匹配企业；企业需先注册后才会出现在这里"
    />
    <article
      v-for="company in query.data.value ?? []"
      :key="company.id"
      class="customer-ticket portal-section-heading"
    >
      <div><h2>{{ company.name }}</h2><small>企业编号：{{ company.code }}</small></div><RouterLink :to="'/customer/companies/' + company.id + '/chat?name=' + encodeURIComponent(company.name)">
        咨询该企业 →
      </RouterLink>
    </article>
    <div class="portal-actions">
      <el-button
        :disabled="page === 1"
        @click="page--"
      >
        上一页
      </el-button><span>第 {{ page }} 页</span><el-button
        :disabled="(query.data.value?.length ?? 0) < 20"
        @click="page++"
      >
        下一页
      </el-button>
    </div>
  </main>
</template>
