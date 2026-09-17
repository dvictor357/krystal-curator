"""Local-LLM addon: a bounded agent over read-only tools (llama.cpp, grammar-constrained
JSON). Off unless `[agent] enabled = true`; nothing outside this package imports it
except the CLI/TUI entry points that check the flag first.
"""

from .llm import AgentRun
from .server import AgentError, LlamaServer
from .tasks import AgentReport, Session

__all__ = ["AgentError", "AgentReport", "AgentRun", "LlamaServer", "Session"]
