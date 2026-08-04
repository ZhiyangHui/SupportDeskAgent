// 前端应用入口只负责装配基础设施，不在这里放置任何具体业务逻辑。
import { VueQueryPlugin } from "@tanstack/vue-query";
import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import router from "./router";
import "./styles/main.css";

const app = createApp(App);

// Pinia 管理浏览器端业务状态，Vue Router 管理页面边界，Vue Query 管理后端数据和缓存。
// 插件必须在 mount 之前完成注册，确保页面组件初始化时能够安全访问这些全局能力。
app.use(createPinia());
app.use(router);
app.use(VueQueryPlugin);
app.mount("#app");
