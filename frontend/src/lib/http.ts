import axios from "axios";

// 基础地址属于部署配置，不应散落在各个 Service 中。启动阶段失败也比首次发送时静默失败更容易排查。
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL;

if(!apiBaseUrl) {
    throw new Error("缺少 VITE_API_BASE_URL，请检查 frontend/.env.local 并重启 Vite");
}

export const httpClient = axios.create({
    // 两端身份分别由后端 HttpOnly Cookie 维护，前端不保存密码或登录令牌。
    withCredentials: true,
    baseURL: apiBaseUrl,
    // 模型推理可能明显慢于普通 CRUD 请求，首版预留一分钟，同时避免请求无限挂起。
    timeout: 60_000,
    headers: {
        "Content-Type": "application/json",
    },
})
