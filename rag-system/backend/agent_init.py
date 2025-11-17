from __future__ import annotations
import warnings

import os
from typing import Any, List

# 暂时注释掉 initialize_agent 的导入以避免错误
# LangChain 1.0+ 中 initialize_agent 已被移除
# TODO: 需要迁移到新的 agent API
try:
    from langchain.agents import initialize_agent
    from langchain.agents.agent_types import AgentType
except ImportError:
    try:
        from langchain_community.agents import initialize_agent
        from langchain_community.agents.agent_types import AgentType
    except ImportError:
        initialize_agent = None
        AgentType = None

try:
    from langchain_ollama import ChatOllama  # type: ignore
except ImportError:  # pragma: no cover
    from langchain_community.chat_models import ChatOllama

from tavily import TavilyClient

from .config import settings
from .services.providers import get_hybrid_retriever
from .tools import DocSearchTool, TavilyTool


def _build_tools() -> List[Any]:
    retriever = get_hybrid_retriever()
    doc_tool = DocSearchTool(retriever=retriever)

    tools: List[Any] = [doc_tool]

    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
    if tavily_key:
        tavily_client = TavilyClient(api_key=tavily_key)
        tools.append(TavilyTool(client=tavily_client))

    return tools


def build_agent() -> Any:
    """
    Construct a LangChain agent connected to local Ollama and retrieval tools.
    """
    if initialize_agent is None or AgentType is None:
        raise ImportError(
            "Could not import initialize_agent or AgentType. "
            "Please ensure langchain or langchain-community is properly installed."
        )

    warnings.warn(
        "initialize_agent is deprecated in LangChain 0.1.0 and will be removed in 1.0. "
        "This should be updated to use create_react_agent when the migration path is clear "
        "for the current LangChain version.",
        FutureWarning,
        stacklevel=2
    )

    tools = _build_tools()

    llm = ChatOllama(
        model=settings.ollama_model,
        temperature=0,
        base_url=settings.ollama_base_url,
        streaming=True,
        num_ctx=8192,
    )

    agent = initialize_agent(
        tools=tools,
        llm=llm,
        agent_type=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True,
    )
    return agent
