"""跨会话偏好只接收受限字段，不允许客户向长期记忆注入系统指令。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class CustomerPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reply_style: Literal["concise", "detailed"] = "concise"
