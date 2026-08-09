import { useMutation } from "@tanstack/vue-query";

import { sendAgentMessage } from "@/services/agent-service";
import { useConversationStore } from "@/stores/conversation";

/** 连接网络请求与会话状态，让页面只关心提交、加载和错误反馈。 */
export function useAgentChat() {
    const conversationStore = useConversationStore();

    const mutation = useMutation({
        mutationFn: sendAgentMessage,
        onSuccess(response) {
            // Service 已校验响应，这里只把可展示内容同步到客户端会话状态。
            conversationStore.appendAgentMessage(response.reply);
        },
        onError(_error, submittedContent) {
            // 请求失败时保留已显示的客户消息；仅在输入框为空时恢复原文，避免覆盖用户新输入。
            conversationStore.restoreDraft(submittedContent);
        },
    });

    function submitDraft(): void {
        // 一次只允许一个模型请求，避免双击造成重复消息、重复工具调用和额外模型费用。
        if (mutation.isPending.value) return;

        const content = conversationStore.takeDraft();
        if (!content) return;

        // 客户消息先本地展示，Agent 回复稍后由 Mutation 成功回调追加。
        conversationStore.appendCustomerMessage(content);
        mutation.mutate(content);
    }

    return {
        submitDraft,
        isPending: mutation.isPending,
        error: mutation.error,
    };


}