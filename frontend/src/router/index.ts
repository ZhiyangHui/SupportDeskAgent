// 路由模块是页面访问的唯一入口，后续登录校验、权限判断和页面标题都在这里集中扩展。
import { createRouter, createWebHistory } from "vue-router";

import SupportDeskView from "@/views/SupportDeskView.vue";

// 使用 History 模式获得正常的业务 URL；部署时需要由网关把未知路径回退到 index.html。
const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      // 当前首页直接承载客服工作台，后续拆分工单中心时只需新增路由，不改入口组件。
      path: "/",
      name: "support-desk",
      component: SupportDeskView,
    },
  ],
});

export default router;
