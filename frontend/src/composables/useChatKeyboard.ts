// 两种聊天输入框共用键盘规则，中文选词确认不能被当作发送操作。
export function useChatKeyboard(canSubmit: () => boolean, submit: () => void) {
  function onChatKeydown(event: Event): void {
    // Element Plus 的事件类型包含普通 Event，在边界处收窄后再读取键盘属性。
    if (!(event instanceof KeyboardEvent)) return;
    // keyCode 229 兼容部分浏览器在输入法确认阶段未正确标记 isComposing 的情况。
    if (event.key !== "Enter" || event.shiftKey || event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    // 长按 Enter、空草稿及请求进行中均不能重复提交。
    if (!event.repeat && canSubmit()) submit();
  }
  return { onChatKeydown };
}
