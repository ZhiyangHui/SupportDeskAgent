"""用 LangChain 回调记录步骤元数据，不记录提示词、参数、原始返回或异常正文。"""

import json
from time import monotonic
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import ToolMessage


class AgentTrace(AsyncCallbackHandler):
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.active: dict[UUID, tuple[dict[str, Any], float]] = {}

    def start(self, run_id: UUID, name: str, kind: str) -> None:
        if len(self.steps) >= 100:
            return
        step = {"name": name, "kind": kind, "status": "running", "duration_ms": 0}
        self.steps.append(step)
        self.active[run_id] = (step, monotonic())

    def finish(self, run_id: UUID, failed: bool = False) -> None:
        value = self.active.pop(run_id, None)
        if value:
            step, started = value
            step.update(
                status="failed" if failed else "succeeded",
                duration_ms=round((monotonic() - started) * 1000),
            )

    async def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        # 只记录明确命名的业务节点，排除 Runnable 内部链和模型输出内容。
        name = kwargs.get("name", "")
        if name in {
            "analyze_request_node",
            "order_workflow_node",
            "assess_after_sales_node",
            "finalize_ticket_node",
            "human_handoff_node",
        }:
            self.start(run_id, name, "node")

    async def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self.finish(run_id)

    async def on_chain_error(
        self, error: BaseException, *, run_id: UUID, **kwargs: Any
    ) -> None:
        self.finish(run_id, True)

    async def on_tool_start(
        self, serialized: dict[str, Any], input_str: str, *, run_id: UUID, **kwargs: Any
    ) -> None:
        self.start(run_id, serialized.get("name", "tool"), "tool")

    async def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        failed = False
        # 工具可能以 Command 返回可恢复错误；调用完成不等于检索成功。
        update = getattr(output, "update", None)
        if isinstance(update, dict):
            failed = bool(update.get("knowledge_error"))
        elif isinstance(output, ToolMessage):
            failed = output.status == "error"
            if isinstance(output.content, str):
                try:
                    payload = json.loads(output.content)
                    failed = failed or (
                        isinstance(payload, dict) and bool(payload.get("error"))
                    )
                except (ValueError, TypeError):
                    pass
        self.finish(run_id, failed)

    async def on_tool_error(
        self, error: BaseException, *, run_id: UUID, **kwargs: Any
    ) -> None:
        self.finish(run_id, True)
