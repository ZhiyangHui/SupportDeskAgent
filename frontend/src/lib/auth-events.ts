// 跨标签页只广播“身份已变化”，不传播账号、密码或凭证；其他页面重新登录以清空旧缓存。
import type { Audience } from "@/services/access-service";
export function notifyAuthChange(audience: Audience): void {
  localStorage.setItem("supportdesk.auth-event", JSON.stringify({ audience, nonce: crypto.randomUUID() }));
}
export function listenForAuthChanges(): void {
  window.addEventListener("storage", (event) => {
    if (event.key !== "supportdesk.auth-event" || !event.newValue) return;
    try {
      const data: unknown = JSON.parse(event.newValue);
      if (typeof data !== "object" || data === null || !("audience" in data)) return;
      if (data.audience !== "customer" && data.audience !== "staff") return;
      if (window.location.pathname.startsWith("/" + data.audience + "/")) {
        window.location.replace("/" + data.audience + "/login");
      }
    } catch { /* 非法通知不影响当前页面，认证有效性始终由后端判断。 */ }
  });
}
