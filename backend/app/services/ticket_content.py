"""只拆分明确的单一售后诉求；复杂自然语言保留原文，不靠关键词猜测故障。"""


def split_order_issue(issue: str) -> tuple[str, str]:
    text = issue.strip()
    # 精确匹配避免把“不退款，只维修”等带否定、组合语义的内容错误改写。
    actions = {"退款", "退货", "换货", "维修", "退货退款"}
    if text in actions or any(text == prefix + action for prefix in ("希望", "申请", "我要") for action in actions):
        return "", text
    return text, ""
