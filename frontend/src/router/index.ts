// 路由模块是页面访问的唯一入口，后续登录校验、权限判断和页面标题都在这里集中扩展。
import { createRouter, createWebHistory } from "vue-router";

import CustomerLayout from "@/views/CustomerLayout.vue";
import CustomerLoginView from "@/views/CustomerLoginView.vue";
import CompanyDirectoryView from "@/views/CompanyDirectoryView.vue";
import StaffCustomersView from "@/views/StaffCustomersView.vue";
import CustomerChatView from "@/views/CustomerChatView.vue";
import CustomerTicketsView from "@/views/CustomerTicketsView.vue";
import CustomerOrdersView from "@/views/CustomerOrdersView.vue";
import StaffLoginView from "@/views/StaffLoginView.vue";
import { getIdentity } from "@/services/access-service";
import TicketCenterView from "@/views/TicketCenterView.vue";
import AgentRunCenterView from "@/views/AgentRunCenterView.vue";

// 使用 History 模式获得正常的业务 URL；部署时需要由网关把未知路径回退到 index.html。
const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      redirect: "/customer/companies",
    },
    { path: "/customer/login", component: CustomerLoginView, meta: { title: "客户登录" } },
    { path: "/customer", component: CustomerLayout, meta: { customer: true }, children: [
      { path: "", redirect: "/customer/companies" },
      { path: "companies", component: CompanyDirectoryView, meta: { title: "选择企业" } },
      { path: "chat", redirect: "/customer/companies" },
      { path: "companies/:companyId/chat", name: "support-desk", component: CustomerChatView, meta: { title: "企业咨询" } },
      { path: "tickets", component: CustomerTicketsView, meta: { title: "我的工单" } },
      { path: "companies/:companyId/orders", component: CustomerOrdersView, meta: { title: "我的模拟订单" } },
    ] },
    { path: "/staff/login", component: StaffLoginView, meta: { title: "企业访问验证" } },
    { path: "/staff", redirect: "/staff/tickets" },
    { path: "/staff/customers", component: StaffCustomersView, meta: { title: "企业客户与会话", staff: true } },
    // 兼容旧书签，但跳转后仍必须经过企业身份验证。
    { path: "/tickets", redirect: "/staff/tickets" },
    { path: "/agent-runs", redirect: "/staff/agent-runs" },
    {
      path: "/staff/tickets",
      name: "ticket-center",
      component: TicketCenterView,
      meta: { title: "企业工单处理", staff: true },
    },
    {
      path: "/staff/agent-runs",
      name: "agent-runs",
      component: AgentRunCenterView,
      meta: { title: "Agent 运行记录", staff: true },
    },
    { path: "/:pathMatch(.*)*", redirect: "/customer/chat" },
  ],
});

// 前端守卫只改善访问体验，真正的权限边界仍是后端每个企业 API 的依赖校验。
router.beforeEach(async (to) => {
  if (!to.meta.staff && !to.meta.customer) return true;
  const audience = to.meta.staff ? "staff" : "customer";
  try { await getIdentity(audience); return true; }
  catch { return "/" + audience + "/login"; }
});

// 页面标题属于路由级元数据，集中维护后不会被业务组件的生命周期覆盖。
router.afterEach((to) => {
  document.title = to.meta.title ? `${String(to.meta.title)} · SupportDesk` : "SupportDesk";
});

export default router;
