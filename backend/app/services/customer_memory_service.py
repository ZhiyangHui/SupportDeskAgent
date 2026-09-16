"""官方 Store 的业务适配：只保存客户显式设置的偏好，按企业和客户双重隔离。"""

from uuid import UUID

from langgraph.store.base import BaseStore

from app.schema.memory import CustomerPreferences


class CustomerMemoryService:
    def __init__(self, store: BaseStore, company_id: UUID, customer_id: UUID):
        self.store = store
        self.namespace = (
            "supportdesk",
            str(company_id),
            str(customer_id),
            "preferences",
        )

    async def read(self) -> CustomerPreferences:
        item = await self.store.aget(self.namespace, "reply")
        return (
            CustomerPreferences.model_validate(item.value)
            if item
            else CustomerPreferences()
        )

    async def save(self, preferences: CustomerPreferences) -> None:
        # 单一稳定键表示覆盖最新偏好，不把每次聊天重复累积成长期事实。
        await self.store.aput(
            self.namespace, "reply", preferences.model_dump(), index=False
        )

    async def clear(self) -> None:
        await self.store.adelete(self.namespace, "reply")
