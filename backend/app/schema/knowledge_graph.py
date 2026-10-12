"""固定的售后领域结构；完整路径避免把不同原因的检查与解决方案错误拼接。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ConceptKind = Literal["category", "symptom", "cause", "check", "solution", "condition"]


class DomainConcept(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)
    # 身份使用稳定编码，不因中文名称调整而生成重复节点。
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,79}$")
    kind: ConceptKind
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)


class DiagnosticPath(BaseModel):
    """路径是一组有条件的解法，不表示客户原因已确认或条件已满足。"""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,79}$")
    category: str
    symptom: str
    cause: str
    checks: list[str] = Field(min_length=1, max_length=10)
    solution: str
    requires: list[str] = Field(min_length=1, max_length=10)
    excludes: list[str] = Field(default_factory=list, max_length=10)
    explanation: str = Field(min_length=1, max_length=1000)
    escalation: str = Field(min_length=1, max_length=500)


class DomainCatalog(BaseModel):
    """独立的通用知识包，不接收客户订单、聊天记录或模型自动发布内容。"""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,79}$")
    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=100)
    maturity: Literal["demo", "verified"]
    provenance: str = Field(min_length=1, max_length=1000)
    nodes: list[DomainConcept] = Field(min_length=1, max_length=500)
    paths: list[DiagnosticPath] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_references(self) -> "DomainCatalog":
        nodes = {node.id: node for node in self.nodes}
        if len(nodes) != len(self.nodes) or len({p.id for p in self.paths}) != len(self.paths):
            raise ValueError("知识节点或路径编码重复")
        used: set[str] = set()
        for path in self.paths:
            refs = [(path.category, "category"), (path.symptom, "symptom"), (path.cause, "cause"),
                    (path.solution, "solution"), *[(key, "check") for key in path.checks],
                    *[(key, "condition") for key in path.requires + path.excludes]]
            for keys in (path.checks, path.requires, path.excludes):
                if len(set(keys)) != len(keys):
                    raise ValueError("步骤或条件不能重复")
            if set(path.requires) & set(path.excludes):
                raise ValueError("同一条件不能同时要求满足和排除")
            for key, kind in refs:
                if key not in nodes or nodes[key].kind != kind:
                    raise ValueError(f"路径 {path.id} 引用了不存在或类型错误的节点 {key}")
                used.add(key)
        if used != set(nodes):
            raise ValueError("知识包包含未关联的孤立节点")
        return self


class GraphStatus(BaseModel):
    enabled: bool
    ready: bool
    message: str
