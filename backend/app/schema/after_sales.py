"""售后预判只生成建议，工具写入授权不属于模型输出。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AfterSalesAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    verdict: Literal["eligible", "needs_info", "manual"]
    explanation: str = Field(min_length=1, max_length=500)
    questions: list[str] = Field(default_factory=list, max_length=4)
    source_numbers: list[int] = Field(default_factory=list, max_length=5)
