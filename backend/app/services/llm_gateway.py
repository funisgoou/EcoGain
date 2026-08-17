"""LLM 网关（AGENT-8）：配置驱动的惰性 client 缓存、reload 失效重建、重试 2 次。
另含 LangChain 消息 → OpenAI 协议消息的统一转换（graph/output 共用）。"""
from __future__ import annotations

import asyncio
import json as _json
import os
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from openai import APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import BaseModel

from app.core.config import get_config
from app.core.logging import get_logger
from app.schemas.common import BizError

log = get_logger(__name__)


def lc_to_openai(messages: list[BaseMessage]) -> list[dict]:
    """LangChain 消息序列 → OpenAI chat 协议消息。

    关键点：tool_calls.function.arguments 必须是 JSON **字符串**（协议规定），
    LangChain 侧是 dict——此处序列化；否则 LiteLLM 网关报
    invalid type: map, expected a string（第二轮工具调用必现）。
    """
    out: list[dict] = []
    for m in messages:
        if isinstance(m, ToolMessage):
            out.append({"role": "tool", "content": str(m.content),
                        "tool_call_id": m.tool_call_id})
        elif isinstance(m, AIMessage):
            entry: dict[str, Any] = {"role": "assistant", "content": m.content or ""}
            if m.tool_calls:
                entry["tool_calls"] = [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"],
                                  "arguments": _json.dumps(c["args"], ensure_ascii=False)}}
                    for c in m.tool_calls
                ]
            out.append(entry)
        else:
            role = "system" if m.type == "system" else "user"
            out.append({"role": role, "content": m.content})
    return out


class LLMGateway:
    def __init__(self) -> None:
        self._client_cache: tuple[tuple, AsyncOpenAI] | None = None  # (配置指纹, client)

    def get_client(self) -> AsyncOpenAI:
        cfg = get_config()
        fp = (cfg.llm_base_url, cfg.llm_api_key_ref, cfg.llm_model)
        if self._client_cache and self._client_cache[0] == fp:
            return self._client_cache[1]  # 配置未变，复用
        api_key = os.environ.get(cfg.llm_api_key_ref, "")
        if not api_key:
            log.warning("llm_api_key_missing", env_name=cfg.llm_api_key_ref)
        client = AsyncOpenAI(base_url=cfg.llm_base_url, api_key=api_key or "unset")
        self._client_cache = (fp, client)
        return client

    def invalidate(self) -> None:
        """reload 后调用（配置指纹变化本身即可触发重建，此方法显式清理）。"""
        self._client_cache = None

    async def chat(self, messages: list[dict], tools: list[dict] | None = None,
                   **kw: Any):
        """统一重试：超时/5xx/限流 → 退避 1s、4s 重试 2 次；每次重试记 warn。"""
        cfg = get_config()
        last_err: Exception | None = None
        for attempt, backoff in enumerate((0, 1, 4), 1):
            if backoff:
                await asyncio.sleep(backoff)
            try:
                return await self.get_client().chat.completions.create(
                    model=cfg.llm_model,
                    messages=messages,
                    tools=tools,
                    temperature=cfg.llm_temperature,
                    **kw,
                )
            except (APITimeoutError, APIStatusError) as e:
                last_err = e
                if attempt == 3:
                    break
                log.warning("llm_retry", attempt=attempt, error=str(e))
        raise BizError(50001, f"LLM 调用失败：{last_err}")

    async def complete(self, prompt: str) -> str:
        """无工具、非流式纯文本补全（摘要等内部调用）。"""
        resp = await self.chat(
            [{"role": "user", "content": prompt}], tools=None, stream=False
        )
        return resp.choices[0].message.content or ""

    async def structured_output(self, messages: list[dict], schema: type[BaseModel],
                                instruction: str) -> BaseModel:
        """结构化输出：JSON 生成 + Pydantic 解析（output.py 用）。

        优先 response_format=json_object（OpenAI 标准模式）；供应商网关不支持时
        自动降级为裸文本 + _extract_json 解析（容忍 markdown 代码块包裹）。
        """
        cfg = get_config()
        payload = messages + [{"role": "system", "content": instruction}]
        last_err: Exception | None = None
        use_json_mode = True  # 首轮带 json_object，失败后降级
        for attempt in range(1, 5):
            backoff = (0, 1, 1, 4)[attempt - 1]
            if backoff:
                await asyncio.sleep(backoff)
            try:
                kwargs: dict[str, Any] = {"response_format": {"type": "json_object"}} \
                    if use_json_mode else {}
                resp = await self.get_client().chat.completions.create(
                    model=cfg.llm_model,
                    messages=payload,
                    temperature=0.1,
                    stream=False,
                    **kwargs,
                )
                raw = resp.choices[0].message.content or ""
                return schema.model_validate_json(_extract_json(raw))
            except (APITimeoutError, APIStatusError) as e:
                last_err = e
                # 4xx 且发生在 json_object 模式下 → 大概率网关不支持，降级重试
                if use_json_mode and isinstance(e, APIStatusError) and 400 <= e.status_code < 500:
                    log.warning("llm_json_mode_unsupported_fallback", status=e.status_code)
                    use_json_mode = False
                    continue
                log.warning("llm_structured_retry", attempt=attempt, error=str(e))
            except ValueError as e:  # JSON 解析/校验失败
                last_err = e
                log.warning("llm_structured_invalid_json", attempt=attempt, error=str(e))
        raise BizError(50001, f"LLM 结构化输出失败：{last_err}")


def _extract_json(raw: str) -> str:
    """从模型输出中提取 JSON 对象文本（容忍 markdown 代码块包裹）。"""
    import json
    import re

    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    json.loads(s)  # 预校验，抛 ValueError 交由上层重试
    return s


llm = LLMGateway()
