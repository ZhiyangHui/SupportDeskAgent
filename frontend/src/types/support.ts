export type MessageRole = "customer" | "agent";

/** 客服会话中的单条消息，后续会与后端消息响应模型保持字段一致。 */
export interface SupportMessage {
  id: string;
  role: MessageRole;
  content: string;
  time: string;
  // Tool Call 元数据与回复文本分离，页面不通过正则猜测 Agent 是否真的执行了副作用。
  toolCall?: {
    name: "create_support_ticket" | "query_support_tickets";
    status: "success";
    ticketCode: string | null;
  };
}

/** 工作台右侧展示的工单摘要，完整工单详情由独立接口按需加载。 */
export interface TicketSummary {
  id: string;
  subject: string;
  status: "处理中" | "等待客户" | "已解决";
  priority: "低" | "中" | "高";
}
