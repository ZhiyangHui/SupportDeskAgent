<script setup lang="ts">
// 服务端身份由 Query 维护，退出只撤销客户会话，不影响独立的企业登录。
import { useQuery, useMutation, useQueryClient } from "@tanstack/vue-query";
import { useRouter } from "vue-router";
import { initializeCustomer, logoutAccount } from "@/services/access-service";
import { useConversationStore } from "@/stores/conversation";
const identity = useQuery({ queryKey: ["customer-identity"], queryFn: initializeCustomer, retry: false, staleTime: 0 });
const router = useRouter();
const cache = useQueryClient();
const conversation = useConversationStore();
const logout = useMutation({ mutationFn: () => logoutAccount("customer"), async onSuccess() {
  await cache.cancelQueries(); cache.clear(); conversation.clearConversation(); await router.replace("/customer/login");
} });
</script>
<template>
  <div class="customer-portal">
    <header class="portal-header">
      <RouterLink
        to="/customer/companies"
        class="portal-brand"
      >
        SupportDesk · 客户服务
      </RouterLink>
      <nav aria-label="客户服务导航">
        <RouterLink to="/customer/companies">
          选择企业
        </RouterLink><RouterLink to="/customer/tickets">
          我的工单
        </RouterLink>
      </nav>
      <span>{{ identity.data.value?.display_name }}</span>
      <el-button
        :loading="logout.isPending.value"
        @click="logout.mutate()"
      >
        退出客户账号
      </el-button>
      <RouterLink to="/staff/login">
        企业员工入口 →
      </RouterLink>
    </header>
    <p
      v-if="logout.isError.value"
      role="alert"
    >
      退出失败，请检查网络后重试。
    </p>
    <main
      v-if="identity.isPending.value"
      class="portal-panel"
    >
      正在验证客户登录……
    </main>
    <main
      v-else-if="identity.isError.value"
      class="portal-panel"
    >
      <p>登录失效或服务不可用。</p><RouterLink to="/customer/login">
        重新登录
      </RouterLink><el-button @click="identity.refetch()">
        重试
      </el-button>
    </main>
    <RouterView
      v-else
      v-slot="{ Component }"
    >
      <!-- 只为业务组件设置上下文 key，不重建 RouterView 自身的路由状态。 -->
      <component
        :is="Component"
        :key="$route.path"
      />
    </RouterView>
  </div>
</template>
