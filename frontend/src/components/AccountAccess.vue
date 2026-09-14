<script setup lang="ts">
// 表单共用校验与反馈，但两端的账号、API 和 Cookie 保持隔离。
import { computed, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { useMutation, useQueryClient } from "@tanstack/vue-query";
import { isAxiosError } from "axios";
import { z } from "zod";
import { accountInputSchema, registrationPasswordSchema, loginAccount, registerAccount, type Audience } from "@/services/access-service";
import { useConversationStore } from "@/stores/conversation";
import { notifyAuthChange } from "@/lib/auth-events";

const props = defineProps<{ audience: Audience }>();
const staff = computed(() => props.audience === "staff");
const registering = ref(false);
const form = reactive({ username: "", password: "", display_name: "", company_code: "", company_name: "" });
const error = ref("");
const notice = ref("");
const router = useRouter();
const cache = useQueryClient();
const conversation = useConversationStore();
const mutation = useMutation({ mutationFn: async () => {
  const basic = accountInputSchema.parse(form);
  const company = staff.value ? { company_code: z.string().min(3).max(50).regex(/^[a-z0-9-]+$/).parse(form.company_code) } : {};
  if (registering.value) {
    registrationPasswordSchema.parse(form.password);
    await registerAccount(props.audience, { ...basic, ...company,
      display_name: z.string().trim().min(1).max(100).parse(form.display_name),
      ...(staff.value ? { company_name: z.string().trim().min(1).max(100).parse(form.company_name) } : {}),
    });
    registering.value = false;
    notice.value = "注册成功，请使用刚创建的账号和密码登录。";
    return;
  }
  await loginAccount(props.audience, { ...basic, ...company });
  notifyAuthChange(props.audience);
  // 账号切换清理旧数据；服务端仍逐次验证，不能用缓存状态代替认证。
  await cache.cancelQueries();
  cache.clear();
  conversation.clearConversation();
  await router.replace(staff.value ? "/staff/customers" : "/customer/companies");
}, onError(problem) {
  const parsed = z.object({ detail: z.string() }).safeParse(isAxiosError(problem) ? problem.response?.data : null);
  error.value = problem instanceof z.ZodError ? (registering.value ? "请检查输入：账号至少3位；注册密码8～20个字符，无字符种类要求；企业编号使用小写字母、数字或连字符。" : "请检查账号、企业编号及密码是否填写完整。") : parsed.success ? parsed.data.detail : "请求失败，请检查后端和网络后重试";
}, onSettled() { form.password = ""; } });
function submit(): void { if (!mutation.isPending.value) { error.value = ""; notice.value = ""; mutation.mutate(); } }
</script>

<template>
  <main class="portal-panel staff-login">
    <p class="eyebrow">
      {{ staff ? '企业员工入口' : '客户服务入口' }}
    </p>
    <h1>{{ registering ? (staff ? '创建企业及首个员工账号' : '注册客户账号') : (staff ? '企业员工登录' : '客户登录') }}</h1>
    <p>{{ staff ? '使用企业编号和员工账号进入本企业工作台。' : '登录后选择要咨询的企业，分别管理您的会话与工单。' }}</p>
    <el-alert
      v-if="staff && registering"
      title="此入口只创建新企业，不会加入已有企业；名称不代表平台资质认证。"
      type="info"
      :closable="false"
    />
    <form @submit.prevent="submit">
      <el-form
        label-position="top"
        :disabled="mutation.isPending.value"
      >
        <el-form-item
          v-if="staff"
          label="企业编号"
        >
          <el-input
            v-model="form.company_code"
            placeholder="例如 acme-support"
          />
        </el-form-item>
        <el-form-item
          v-if="staff && registering"
          label="企业名称"
        >
          <el-input v-model="form.company_name" />
        </el-form-item>
        <el-form-item
          v-if="registering"
          :label="staff ? '员工姓名' : '您的称呼'"
        >
          <el-input v-model="form.display_name" />
        </el-form-item>
        <el-form-item label="账号">
          <el-input
            v-model="form.username"
            autocomplete="username"
          />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :autocomplete="registering ? 'new-password' : 'current-password'"
          />
        </el-form-item>
      </el-form>
      <el-alert
        v-if="error"
        :title="error"
        type="error"
        :closable="false"
      />
      <el-alert
        v-if="notice"
        :title="notice"
        type="success"
        :closable="false"
      />
      <div class="portal-actions">
        <el-button
          native-type="submit"
          type="primary"
          :loading="mutation.isPending.value"
        >
          {{ registering ? '注册' : '登录' }}
        </el-button><el-button
          :disabled="mutation.isPending.value"
          @click="registering = !registering; error = ''; notice = ''"
        >
          {{ registering ? '已有账号，去登录' : staff ? '创建新企业' : '注册客户账号' }}
        </el-button>
      </div>
    </form>
    <RouterLink :to="staff ? '/customer/login' : '/staff/login'">
      {{ staff ? '我是客户，去客户登录' : '我是企业员工，去企业登录' }} →
    </RouterLink>
  </main>
</template>
