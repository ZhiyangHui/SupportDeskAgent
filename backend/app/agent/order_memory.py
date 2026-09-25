"""旧检查点路径兼容入口；业务实现已迁至 memory/order_memory.py，新代码不得从这里导入。"""

# 历史 Checkpoint 记录了旧模块路径，保留类的转发即可恢复，不复制任何状态逻辑。
from app.agent.memory.order_memory import OrderChoice, OrderMemory

__all__ = ["OrderChoice", "OrderMemory"]
