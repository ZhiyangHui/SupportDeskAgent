"""结构优先的分块：标题决定边界，长度只用于拆分过长章节，不改写业务规则。"""
import re

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.schema.knowledge import DraftChunk

CHUNKING_VERSION = "structure-v1"


def build_draft(title: str, content: str) -> tuple[list[DraftChunk], list[str]]:
    """兼容 Markdown 和常见中文标题；无法识别的文本明确提示人工检查。"""
    lines: list[str] = []
    warnings: list[str] = []
    fence = ""
    headings = 0
    # 无标记的短标题只识别明确的业务词，不把普通短句或编号列表猜成章节。
    subtitles = {"退货", "换货", "维修", "安装与使用", "退货与维修"}
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            if not fence:
                fence = stripped[:3]
            elif stripped.startswith(fence):
                fence = ""
            lines.append(line)
            continue
        if not fence:
            if re.match(r"^[一二三四五六七八九十百]+、\S", stripped):
                line = "## " + stripped
            elif stripped in subtitles:
                line = "### " + stripped
            if re.match(r"^#{1,6}\s+\S", line.strip()):
                headings += 1
        lines.append(line)
    normalized = "\n".join(lines)
    if not headings:
        warnings.append("未识别到章节标题，已按段落兜底；建议在原文使用 Markdown 标题。")
    # 标题连续出现且没有正文时，父标题可以是正常容器，仍提示检查空章节。
    if re.search(r"(?m)^#{1,6}\s+[^\n]+\n\s*#{1,6}\s|^#{1,6}\s+[^\n]+\s*\Z", normalized):
        warnings.append("部分标题直接连接下级标题或文末，请检查是否为正常目录层级，或遗漏了正文。")
    sections = MarkdownHeaderTextSplitter(headers_to_split_on=[("#" * i, f"h{i}") for i in range(1, 7)]).split_text(normalized)
    result: list[DraftChunk] = []
    for section in sections:
        path = [title]
        for value in section.metadata.values():
            if value != path[-1]:
                path.append(value)
        body = section.page_content.strip()
        if not body:
            continue
        # 500 是软上限：完整章节不超过 800 字符就保留，避免把条件、例外强行拆开。
        pieces = [body] if len(body) <= 800 else RecursiveCharacterTextSplitter(
            chunk_size=500, chunk_overlap=60, separators=["\n\n", "\n", "。", "；", " ", ""]
        ).split_text(body)
        if len(pieces) > 1:
            warnings.append(f"章节「{' / '.join(path)}」较长，已拆分；请检查限制条件是否仍完整。")
        result.extend(DraftChunk(heading_path=" / ".join(path), content=piece) for piece in pieces)
    return result, list(dict.fromkeys(warnings))


def indexed_text(path: str, content: str) -> str:
    """向量检索与回答使用相同上下文；数据库正文独立保存，方便与原文核对。"""
    return f"所属章节：{path}\n\n{content}" if path else content
