<script setup lang="ts">
// 企业模块共用导航，退出时清理服务端缓存，避免下一次进入时闪现上一个会话的数据。
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { useRouter } from "vue-router";
import { logoutStaff, checkStaffSession } from "@/services/access-service";
import { Building2, Headphones, Users, TicketCheck, Bot, ExternalLink, LogOut } from "@lucide/vue";
const identity = useQuery({ queryKey: ["staff-identity"], queryFn: checkStaffSession, retry: false });

const queryClient = useQueryClient();
const router = useRouter();
const logout = useMutation({
  mutationFn: logoutStaff,
  async onSuccess() {
    await queryClient.cancelQueries();
    queryClient.clear();
    await router.replace("/staff/login");
  },
});
</script>

<template>
  <aside
    class="sidebar staff-sidebar"
    aria-label="企业工作台导航"
  >
    <div class="staff-brand">
      <Headphones
        :size="24"
        aria-hidden="true"
      />
      <div class="staff-brand-text">
        <strong>SupportDesk</strong><span>企业工作台</span>
      </div>
    </div>
    <!-- 图标与文字使用明确的子元素，避免纯文本落入旧导航的固定宽度网格列。 -->
    <nav
      class="staff-menu"
      aria-label="企业功能"
    >
      <RouterLink
        class="staff-menu-link"
        active-class="active"
        to="/staff/customers"
        aria-label="客户与会话"
        title="客户与会话"
      >
        <Users
          :size="19"
          aria-hidden="true"
        /><span class="staff-menu-label">客户与会话</span>
      </RouterLink>
      <RouterLink
        class="staff-menu-link"
        active-class="active"
        to="/staff/tickets"
        aria-label="工单处理"
        title="工单处理"
      >
        <TicketCheck
          :size="19"
          aria-hidden="true"
        /><span class="staff-menu-label">工单处理</span>
      </RouterLink>
      <RouterLink
        class="staff-menu-link"
        active-class="active"
        to="/staff/agent-runs"
        aria-label="Agent 运行记录"
        title="Agent 运行记录"
      >
        <Bot
          :size="19"
          aria-hidden="true"
        /><span class="staff-menu-label">Agent 运行记录</span>
      </RouterLink>
    </nav>
    <!-- 账号信息和操作单独布局，长名称省略但保留 title，不挤压菜单或退出按钮。 -->
    <div class="staff-account">
      <div
        class="staff-account-identity"
        :title="identity.data.value?.company_name ?? undefined"
      >
        <Building2
          :size="20"
          aria-hidden="true"
        />
        <div class="staff-account-text">
          <strong>{{ identity.data.value?.company_name || '企业工作台' }}</strong><small>{{ identity.data.value?.display_name || '正在加载账号……' }}</small>
        </div>
      </div>
      <RouterLink
        v-if="identity.isError.value"
        to="/staff/login"
        class="staff-account-link"
      >
        登录失效或服务不可用，重新登录
      </RouterLink>
      <RouterLink
        to="/customer/companies"
        class="staff-account-link"
        aria-label="打开客户入口"
        title="打开客户入口"
      >
        <ExternalLink
          :size="17"
          aria-hidden="true"
        /><span class="staff-action-label">打开客户入口</span>
      </RouterLink>
      <el-button
        :loading="logout.isPending.value"
        class="staff-logout"
        aria-label="退出企业工作台"
        title="退出企业工作台"
        @click="logout.mutate()"
      >
        <LogOut
          :size="17"
          aria-hidden="true"
        /><span class="staff-action-label">退出企业工作台</span>
      </el-button>
      <small v-if="logout.isError.value">退出失败，请检查网络后重试</small>
    </div>
  </aside>
</template>

<style scoped>
/* 企业导航不复用旧会话页的 nav-item/sidebar-status，避免网格列和响应式规则互相覆盖。 */
.staff-sidebar { min-width: 0; gap: 28px; }
.staff-brand { display: flex; align-items: center; gap: 12px; padding: 0 8px; }
.staff-brand svg, .staff-menu-link svg, .staff-account svg { flex: 0 0 auto; }
.staff-brand-text { min-width: 0; }
.staff-brand-text strong { display: block; font-size: 16px; }
.staff-brand-text span { display: block; margin-top: 5px; color: #aac6b9; font-size: 12px; }
.staff-menu { display: flex; flex-direction: column; gap: 8px; }
.staff-menu-link { display: flex; align-items: center; gap: 12px; min-height: 46px; padding: 12px; border-radius: 10px; color: #bbd2c8; text-decoration: none; }
.staff-menu-label { min-width: 0; white-space: nowrap; font-size: 14px; line-height: 22px; }
.staff-menu-link:hover, .staff-menu-link.active { color: #fff; background: #ffffff1c; }
.staff-menu-link:focus-visible, .staff-account-link:focus-visible { outline: 2px solid #d8f06d; outline-offset: 3px; }
.staff-account { display: flex; flex-direction: column; align-items: stretch; gap: 16px; margin-top: auto; padding: 16px 12px; border: 1px solid #ffffff18; border-radius: 12px; background: #ffffff0c; }
.staff-account-identity { display: flex; align-items: center; gap: 10px; min-width: 0; }
.staff-account-text { min-width: 0; }
.staff-account-text strong, .staff-account-text small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.staff-account-text strong { font-size: 14px; font-weight: 600; }
.staff-account-text small { margin-top: 5px; font-size: 12px; color: #aac6b9; }
.staff-account-link { display: flex; align-items: center; gap: 8px; color: #d3e5dc; font-size: 13px; line-height: 20px; text-decoration: none; }
.staff-account-link:hover { color: #e1f6a6; }
.staff-logout { width: 100%; margin: 0; --el-button-text-color: #e0eee7; --el-button-bg-color: transparent; --el-button-border-color: #ffffff30; --el-button-hover-text-color: #fff; --el-button-hover-bg-color: #ffffff18; --el-button-hover-border-color: #ffffff60; }
.staff-action-label { margin-left: 4px; white-space: nowrap; }
/* 中屏使用图标栏，保留可访问名称和悬停提示，不把文字压成竖排。 */
@media (min-width: 841px) and (max-width: 1100px) {
  .staff-brand { justify-content: center; padding: 0; }
  .staff-brand-text, .staff-menu-label, .staff-account-text, .staff-action-label { display: none; }
  .staff-menu-link { justify-content: center; padding: 12px 0; }
  .staff-account { padding: 12px 6px; }
  .staff-account-identity, .staff-account-link { justify-content: center; }
  .staff-logout { padding: 8px; }
}
/* 手机端改为顶部菜单，仍能切换模块和退出，不沿用旧页面直接隐藏导航的规则。 */
@media (max-width: 840px) {
  .staff-sidebar { display: flex; padding: 18px 14px; gap: 16px; }
  .staff-menu { flex-direction: row; flex-wrap: wrap; gap: 6px; }
  .staff-menu-link { gap: 7px; padding: 9px; min-height: 40px; }
  .staff-menu-label { font-size: 13px; }
  .staff-account { flex-direction: row; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 0; padding: 12px; }
  .staff-account-identity { flex: 1 1 100%; }
  .staff-logout { width: auto; margin-left: auto; }
}
</style>
