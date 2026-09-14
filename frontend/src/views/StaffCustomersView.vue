<script setup lang="ts">
// 客户列表、会话和消息分别查询，选择变化会切换 Query key，避免把客户 A 的消息展示给 B。
import { computed, ref, watch } from "vue";
import { useQuery } from "@tanstack/vue-query";
import StaffNavigation from "@/components/StaffNavigation.vue";
import { getStaffMessages, listStaffConversations, listStaffCustomers } from "@/services/staff-customer-service";
const page = ref(1);
const keyword = ref("");
const selected = ref<string | null>(null);
const conversation = ref<string | null>(null);
const historyPage = ref(1);
watch(keyword, () => { page.value = 1; selected.value = null; });
watch(selected, () => { conversation.value = null; historyPage.value = 1; });
const customers = useQuery({ queryKey: computed(() => ["staff-customers", page.value, keyword.value]), queryFn: () => listStaffCustomers(page.value, keyword.value) });
const histories = useQuery({ queryKey: computed(() => ["staff-conversations", selected.value, historyPage.value]), queryFn: () => listStaffConversations(selected.value ?? undefined, historyPage.value), enabled: computed(() => selected.value !== null) });
const messages = useQuery({ queryKey: computed(() => ["staff-conversation", conversation.value]), queryFn: () => getStaffMessages(conversation.value as string), enabled: computed(() => conversation.value !== null) });
</script>
<template>
  <main class="app-shell">
    <StaffNavigation /><section class="workspace ticket-workspace">
      <div class="portal-panel">
        <h1>客户与会话</h1><p>仅显示曾向本企业咨询的客户。选择客户查看历史、处理工单；当前会话为只读，不提供实时人工接管。</p>
        <el-input
          v-model="keyword"
          placeholder="搜索客户称呼"
          clearable
        />
        <p v-if="customers.isLoading.value">
          加载中……
        </p><div v-else-if="customers.isError.value">
          <p>客户加载失败</p><el-button @click="customers.refetch()">
            重试
          </el-button>
        </div><el-empty
          v-else-if="!customers.data.value?.length"
          description="暂无咨询客户"
        />
        <article
          v-for="customer in customers.data.value ?? []"
          :key="customer.id"
          class="customer-ticket portal-section-heading"
        >
          <div><strong>{{ customer.display_name }}</strong><p>{{ customer.conversation_count }} 段会话 · 客户 {{ customer.id.slice(0, 8) }}</p></div><el-button @click="selected = customer.id">
            查看会话
          </el-button><RouterLink :to="'/staff/tickets?customer_id=' + customer.id">
            处理该客户工单
          </RouterLink>
        </article>
        <div class="portal-actions">
          <el-button
            :disabled="page === 1"
            @click="page--"
          >
            上一页
          </el-button><span>第 {{ page }} 页</span><el-button
            :disabled="(customers.data.value?.length ?? 0) < 20"
            @click="page++"
          >
            下一页
          </el-button>
        </div>
        <section v-if="selected">
          <h2>该客户的会话</h2><p v-if="histories.isLoading.value">
            加载中……
          </p><div v-if="histories.isError.value">
            会话加载失败 <el-button @click="histories.refetch()">
              重试
            </el-button>
          </div>
          <article
            v-for="item in histories.data.value ?? []"
            :key="item.id"
            class="customer-ticket"
          >
            <el-button @click="conversation = item.id">
              查看 {{ new Date(item.updated_at).toLocaleString('zh-CN') }} 的会话
            </el-button> <RouterLink :to="'/staff/tickets?create=1&conversation_id=' + item.id">
              为此会话建单
            </RouterLink>
          </article>
          <div class="portal-actions">
            <el-button
              :disabled="historyPage === 1"
              @click="historyPage--"
            >
              上一页会话
            </el-button><el-button
              :disabled="(histories.data.value?.length ?? 0) < 20"
              @click="historyPage++"
            >
              下一页会话
            </el-button>
          </div>
        </section>
        <section v-if="conversation">
          <h2>会话内容（只读）</h2><p v-if="messages.isLoading.value">
            加载中……
          </p><div v-if="messages.isError.value">
            消息加载失败 <el-button @click="messages.refetch()">
              重试
            </el-button>
          </div><article
            v-for="message in messages.data.value ?? []"
            :key="message.id"
            class="customer-message"
          >
            <small>{{ message.role === 'customer' ? '客户' : '智能客服' }}</small><p>{{ message.content }}</p>
          </article>
        </section>
      </div>
    </section>
  </main>
</template>
