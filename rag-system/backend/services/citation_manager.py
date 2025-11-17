"""
引用管理器 - 统一管理文档和网络搜索的引用
提供清晰的来源标识和引用格式化
"""

from __future__ import annotations
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass
from enum import Enum
import re
from urllib.parse import urlparse

from ..utils.logger import get_logger


class SourceType(str, Enum):
    """来源类型枚举"""
    DOCUMENT = "document"  # 上传文档
    WEB = "web"  # 网络搜索
    KNOWLEDGE_BASE = "knowledge_base"  # 知识库
    CODE = "code"  # 代码文件


class CitationConfidence(str, Enum):
    """引用置信度枚举"""
    HIGH = "high"  # 高置信度 - 直接相关
    MEDIUM = "medium"  # 中等置信度 - 部分相关
    LOW = "low"  # 低置信度 - 弱相关


@dataclass
class CitationInfo:
    """引用信息数据结构"""
    source_type: SourceType
    source: str  # 来源名称或URL
    title: Optional[str] = None  # 标题
    page: Optional[int] = None  # 页码
    snippet: str = ""  # 引用片段
    score: float = 0.0  # 相关性分数
    confidence: CitationConfidence = CitationConfidence.MEDIUM
    url: Optional[str] = None  # 完整URL（网络来源）
    file_path: Optional[str] = None  # 文件路径（文档来源）
    published_date: Optional[str] = None  # 发布日期
    authors: Optional[List[str]] = None  # 作者列表
    chunks: List[int] = None  # 关联的chunk ID列表

    def __post_init__(self):
        if self.chunks is None:
            self.chunks = []


class CitationManager:
    """引用管理器"""

    def __init__(self):
        self.logger = get_logger(__name__)
        self.citation_counter = 0

    def create_citation_from_document(self, doc: Dict[str, Any]) -> CitationInfo:
        """
        从文档数据创建引用信息

        Args:
            doc: 文档数据

        Returns:
            CitationInfo: 引用信息
        """
        metadata = doc.get("metadata", {}) or {}
        text = (doc.get("text") or metadata.get("text", "")).strip()

        citation = CitationInfo(
            source_type=SourceType.DOCUMENT,
            source=metadata.get("source") or doc.get("source", "未知文档"),
            title=metadata.get("title") or metadata.get("source"),
            page=self._parse_page(metadata.get("page", doc.get("page"))),
            snippet=text[:240] + "..." if len(text) > 240 else text,
            score=float(metadata.get("score", doc.get("score", 0.0)) or 0.0),
            confidence=self._determine_confidence(float(doc.get("score", 0.0))),
            file_path=metadata.get("file_path"),
            chunks=[metadata.get("chunk_id")] if metadata.get("chunk_id") else [],
        )

        return citation

    def create_citation_from_web(self, doc: Dict[str, Any]) -> CitationInfo:
        """
        从网络搜索结果创建引用信息

        Args:
            doc: 网络搜索结果数据

        Returns:
            CitationInfo: 引用信息
        """
        metadata = doc.get("metadata", {}) or {}
        content = (doc.get("content") or doc.get("text", "")).strip()

        citation = CitationInfo(
            source_type=SourceType.WEB,
            source=doc.get("url", ""),
            title=doc.get("title", ""),
            snippet=content[:240] + "..." if len(content) > 240 else content,
            score=float(doc.get("score", 0.0)),
            confidence=self._determine_confidence(float(doc.get("score", 0.0))),
            url=doc.get("url"),
            published_date=metadata.get("published_date") or doc.get("published_date"),
        )

        return citation

    def format_citation(self, citation: CitationInfo, format_type: str = "markdown") -> str:
        """
        格式化引用

        Args:
            citation: 引用信息
            format_type: 格式类型 ("markdown", "plain", "html")

        Returns:
            str: 格式化的引用字符串
        """
        if format_type == "markdown":
            return self._format_markdown(citation)
        elif format_type == "plain":
            return self._format_plain(citation)
        elif format_type == "html":
            return self._format_html(citation)
        else:
            return self._format_markdown(citation)

    def _format_markdown(self, citation: CitationInfo) -> str:
        """Markdown格式化"""
        parts = []

        # 来源标识符
        if citation.source_type == SourceType.DOCUMENT:
            source_text = citation.source
            if citation.page:
                source_text += f" P.{citation.page}"
            parts.append(f"**📄 {source_text}**")
        elif citation.source_type == SourceType.WEB:
            if citation.url:
                if citation.title:
                    parts.append(f"**🌐 [{citation.title}]({citation.url})**")
                else:
                    parts.append(f"**🌐 [来源]({citation.url})**")
            else:
                parts.append(f"**🌐 {citation.title or '网络来源'}**")
        else:
            parts.append(f"**{citation.source}**")

        # 添加置信度标识
        confidence_emoji = {
            CitationConfidence.HIGH: "🟢",
            CitationConfidence.MEDIUM: "🟡",
            CitationConfidence.LOW: "🔴"
        }
        parts.append(f"{confidence_emoji.get(citation.confidence, '🟡')} 置信度: {citation.confidence.value}")

        # 添加发布日期（网络来源）
        if citation.published_date and citation.source_type == SourceType.WEB:
            parts.append(f"📅 {citation.published_date}")

        # 添加作者信息
        if citation.authors:
            authors_text = ", ".join(citation.authors[:3])
            if len(citation.authors) > 3:
                authors_text += f" 等 {len(citation.authors)}人"
            parts.append(f"✍️ {authors_text}")

        return " | ".join(parts)

    def _format_plain(self, citation: CitationInfo) -> str:
        """纯文本格式化"""
        parts = [citation.source]

        if citation.page:
            parts.append(f"Page {citation.page}")

        if citation.title:
            parts.append(f'"{citation.title}"')

        if citation.url:
            parts.append(f"URL: {citation.url}")

        return " - ".join(parts)

    def _format_html(self, citation: CitationInfo) -> str:
        """HTML格式化"""
        parts = []

        source_icon = {
            SourceType.DOCUMENT: "📄",
            SourceType.WEB: "🌐",
            SourceType.KNOWLEDGE_BASE: "📚",
            SourceType.CODE: "💻"
        }

        parts.append(f"<span class='citation-source'>{source_icon.get(citation.source_type, '📎')}")

        if citation.source_type == SourceType.WEB and citation.url:
            if citation.title:
                parts.append(f"<a href='{citation.url}' target='_blank' class='citation-link'>{citation.title}</a>")
            else:
                parts.append(f"<a href='{citation.url}' target='_blank' class='citation-link'>{citation.url}</a>")
        else:
            parts.append(f"<span class='citation-title'>{citation.source}</span>")

        if citation.page:
            parts.append(f"<span class='citation-page'>P.{citation.page}</span>")

        parts.append("</span>")

        confidence_class = f"citation-confidence-{citation.confidence.value}"
        parts.append(f"<span class='citation-confidence {confidence_class}'>{citation.confidence.value}</span>")

        return " ".join(parts)

    def deduplicate_citations(self, citations: List[CitationInfo]) -> List[CitationInfo]:
        """
        去重引用

        Args:
            citations: 引用列表

        Returns:
            List[CitationInfo]: 去重后的引用列表
        """
        unique_citations = []
        seen_keys: Set[str] = set()

        for citation in citations:
            # 创建唯一键
            if citation.source_type == SourceType.WEB:
                key = f"web:{citation.url}"
            else:
                key = f"doc:{citation.source}:{citation.page}"

            if key not in seen_keys:
                seen_keys.add(key)
                unique_citations.append(citation)

        return unique_citations

    def group_citations_by_type(self, citations: List[CitationInfo]) -> Dict[SourceType, List[CitationInfo]]:
        """
        按类型分组引用

        Args:
            citations: 引用列表

        Returns:
            Dict[SourceType, List[CitationInfo]]: 按类型分组的引用
        """
        grouped = {}
        for citation in citations:
            if citation.source_type not in grouped:
                grouped[citation.source_type] = []
            grouped[citation.source_type].append(citation)
        return grouped

    def create_bibliography(self, citations: List[CitationInfo], style: str = "apa") -> List[str]:
        """
        创建参考文献列表

        Args:
            citations: 引用列表
            style: 引用样式 ("apa", "mla", "chicago")

        Returns:
            List[str]: 参考文献列表
        """
        bibliography = []

        for i, citation in enumerate(citations, 1):
            if style == "apa":
                entry = self._create_apa_citation(citation, i)
            elif style == "mla":
                entry = self._create_mla_citation(citation, i)
            elif style == "chicago":
                entry = self._create_chicago_citation(citation, i)
            else:
                entry = self._create_apa_citation(citation, i)

            bibliography.append(entry)

        return bibliography

    def _create_apa_citation(self, citation: CitationInfo, index: int) -> str:
        """创建APA格式引用"""
        if citation.source_type == SourceType.WEB:
            authors = f"{', '.join(citation.authors)}" if citation.authors else ""
            year = citation.published_date[:4] if citation.published_date else "n.d."
            title = citation.title or "无标题"
            url = citation.url or ""

            if authors:
                return f"[{index}] {authors} ({year}). *{title}*. Retrieved from {url}"
            else:
                return f"[{index}] {title} ({year}). Retrieved from {url}"
        else:
            # 文档引用
            source = citation.source
            page = f"p. {citation.page}" if citation.page else ""
            return f"[{index}] {source} ({page})"

    def _create_mla_citation(self, citation: CitationInfo, index: int) -> str:
        """创建MLA格式引用"""
        if citation.source_type == SourceType.WEB:
            authors = f"{', '.join(citation.authors)}" if citation.authors else ""
            title = citation.title or "无标题"
            website = urlparse(citation.url or "").netloc or "未知网站"
            date = citation.published_date or "n.d."
            url = citation.url or ""

            if authors:
                return f"[{index}] {authors}. \"{title}.\" *{website}*, {date}, {url}."
            else:
                return f"[{index}] \"{title}.\" *{website}*, {date}, {url}."
        else:
            source = citation.source
            page = citation.page or ""
            return f"[{index}] *{source}*. {page}."

    def _create_chicago_citation(self, citation: CitationInfo, index: int) -> str:
        """创建Chicago格式引用"""
        if citation.source_type == SourceType.WEB:
            authors = f"{', '.join(citation.authors)}" if citation.authors else ""
            title = citation.title or "无标题"
            website = urlparse(citation.url or "").netloc or "未知网站"
            date = citation.published_date or "n.d."
            url = citation.url or ""

            if authors:
                return f"[{index}] {authors}. \"{title}.\" {website}. {date}. {url}."
            else:
                return f"[{index}] \"{title}.\" {website}. {date}. {url}."
        else:
            source = citation.source
            page = citation.page or ""
            return f"[{index}] *{source}*. {page}."

    def get_source_statistics(self, citations: List[CitationInfo]) -> Dict[str, Any]:
        """
        获取引用统计信息

        Args:
            citations: 引用列表

        Returns:
            Dict[str, Any]: 统计信息
        """
        grouped = self.group_citations_by_type(citations)

        stats = {
            "total_citations": len(citations),
            "by_type": {source_type.value: len(cits) for source_type, cits in grouped.items()},
            "confidence_distribution": {
                "high": sum(1 for c in citations if c.confidence == CitationConfidence.HIGH),
                "medium": sum(1 for c in citations if c.confidence == CitationConfidence.MEDIUM),
                "low": sum(1 for c in citations if c.confidence == CitationConfidence.LOW),
            },
            "average_score": sum(c.score for c in citations) / len(citations) if citations else 0.0,
            "unique_sources": len(set(c.source for c in citations)),
        }

        return stats

    def _parse_page(self, page_value: Any) -> Optional[int]:
        """解析页码"""
        if page_value is None:
            return None
        try:
            return int(page_value)
        except (ValueError, TypeError):
            return None

    def _determine_confidence(self, score: float) -> CitationConfidence:
        """根据分数确定置信度"""
        if score >= 0.8:
            return CitationConfidence.HIGH
        elif score >= 0.5:
            return CitationConfidence.MEDIUM
        else:
            return CitationConfidence.LOW

    def create_interactive_references(self, citations: List[CitationInfo]) -> str:
        """
        创建交互式引用HTML

        Args:
            citations: 引用列表

        Returns:
            str: 交互式引用HTML
        """
        if not citations:
            return ""

        html_parts = ['<div class="citations-container">']
        html_parts.append('<h4>📚 参考来源</h4>')

        grouped = self.group_citations_by_type(citations)

        for source_type, type_citations in grouped.items():
            type_icons = {
                SourceType.DOCUMENT: "📄 文档",
                SourceType.WEB: "🌐 网络",
                SourceType.KNOWLEDGE_BASE: "📚 知识库",
                SourceType.CODE: "💻 代码"
            }

            html_parts.append(f'<div class="citation-group {source_type.value}">')
            html_parts.append(f'<h5>{type_icons.get(source_type, source_type.value)} ({len(type_citations)})</h5>')

            for i, citation in enumerate(type_citations, 1):
                citation_html = self._format_html(citation)
                snippet = citation.snippet[:100] + "..." if len(citation.snippet) > 100 else citation.snippet

                html_parts.append(f'''
                <div class="citation-item" data-citation-id="{i}">
                    <div class="citation-header">
                        {citation_html}
                    </div>
                    <div class="citation-snippet" style="display:none;">
                        <p><em>"{snippet}"</em></p>
                        <div class="citation-score">相关性: {citation.score:.2f}</div>
                    </div>
                </div>
                ''')

            html_parts.append('</div>')

        html_parts.append('</div>')

        # 添加JavaScript交互
        js_code = '''
        <script>
        document.querySelectorAll('.citation-item').forEach(item => {
            item.addEventListener('click', function() {
                const snippet = this.querySelector('.citation-snippet');
                if (snippet.style.display === 'none') {
                    snippet.style.display = 'block';
                } else {
                    snippet.style.display = 'none';
                }
            });
        });
        </script>
        '''

        return "\n".join(html_parts) + js_code


# 全局实例
citation_manager = CitationManager()