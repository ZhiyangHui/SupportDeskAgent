"""旧检查点路径兼容入口；业务实现已迁至 memory/comment_memory.py，新代码不得从这里导入。"""

# 未完成的补充草稿需要按原模块名反序列化；统一转发到新类，保持类型身份一致。
from app.agent.memory.comment_memory import CommentMemory

__all__ = ["CommentMemory"]
