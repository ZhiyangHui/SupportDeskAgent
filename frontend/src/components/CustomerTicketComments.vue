<script setup lang="ts">
// 展开后才加载修改与补充记录，服务端数据交给 Query 管理，不能复用企业内部备注接口。
import { computed, ref } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { listMyTicketComments } from "@/services/customer-service";

const props = defineProps<{ ticketId: string }>();
const page = ref(1);
const comments = useQuery({
  queryKey: computed(() => ["customer-ticket-comments", props.ticketId, page.value]),
  queryFn: () => listMyTicketComments(props.ticketId, page.value),
});
</script>

<template>
  <section aria-label="我的修改与补充记录">
    <p v-if="comments.isPending.value">
      正在加载修改与补充记录……
    </p>
    <el-alert
      v-else-if="comments.isError.value"
      title="修改与补充记录加载失败，请刷新重试"
      type="error"
      :closable="false"
    />
    <p v-else-if="!comments.data.value?.length">
      暂无修改与补充记录
    </p>
    <article
      v-for="comment in comments.data.value ?? []"
      :key="comment.id"
    >
      <small>{{ new Date(comment.created_at).toLocaleString('zh-CN') }}</small>
      <p class="comment-content">
        {{ comment.content }}
      </p>
    </article>
    <div class="portal-actions">
      <el-button
        :disabled="page === 1 || comments.isFetching.value"
        @click="page--"
      >
        上一页
      </el-button>
      <el-button
        :disabled="(comments.data.value?.length ?? 0) < 20 || comments.isFetching.value"
        @click="page++"
      >
        下一页
      </el-button>
      <el-button
        :loading="comments.isFetching.value"
        @click="comments.refetch()"
      >
        刷新记录
      </el-button>
    </div>
  </section>
</template>

<style scoped>
.comment-content { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
