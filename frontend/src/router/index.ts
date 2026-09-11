// 路由模块是页面访问的唯一入口，后续登录校验、权限判断和页面标题都在这里集中扩展。
import { createRouter, createWebHistory } from "vue-router";

import SupportDeskView from "@/views/SupportDeskView.vue";
import TicketCenterView from "@/views/TicketCenterView.vue";

// 使用 History 模式获得正常的业务 URL；部署时需要由网关把未知路径回退到 index.html。
const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      // 首页承载实时会话，工单中心使用独立路由，避免两类复杂业务挤在同一个组件中。
      path: "/",
      name: "support-desk",
      component: SupportDeskView,
    },
    {
      path: "/tickets",
      name: "ticket-center",
      component: TicketCenterView,
      meta: { title: "工单中心" },
    },
  ],
});

// 页面标题属于路由级元数据，集中维护后不会被业务组件的生命周期覆盖。
router.afterEach((to) => {
  document.title = to.meta.title ? `${String(to.meta.title)} · SupportDesk` : "SupportDesk";
});

export default router;
