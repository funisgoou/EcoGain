"""LangGraph 分析图与流式映射（AGENT-1 三节点循环 / AGENT-9 事件→WS 消息）。"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.analysis.context import build_initial_state
from app.analysis.output import generate_structured_output
from app.analysis.state import AnalysisState
from app.analysis.tools import ALL_TOOLS, TOOL_REGISTRY
from app.core.config import get_config
from app.core.logging import get_logger
from app.db.mysql import new_session
from app.models import AnalysisTask
from app.schemas import ws as wsmsg
from app.schemas.common import BizError
from app.services import message_service, result_service, summary_service
from app.services.llm_gateway import lc_to_openai, llm
from app.ws.manager import MANAGER

log = get_logger(__name__)


def _openai_to_lc(msg_dict: dict) -> AIMessage:
    """OpenAI 响应 → AIMessage（保留 tool_calls）。"""
    m = msg_dict
    tool_calls = [
        {"id": tc["id"], "name": tc["function"]["name"],
         "args": _parse_args(tc["function"]["arguments"])}
        for tc in (m.get("tool_calls") or [])
    ]
    return AIMessage(content=m.get("content") or "", tool_calls=tool_calls or None)


def _parse_args(raw: Any) -> dict:
    import json

    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}


async def agent_node(state: AnalysisState) -> dict:
    """单步 LLM 调用（绑定 5 工具）；流式文本增量由外层捕获，这里返回 messages 追加。"""
    resp = await llm.chat(lc_to_openai(state["messages"]), tools=ALL_TOOLS, stream=False)
    choice = resp.choices[0]
    ai_msg = _openai_to_lc(
        {"content": choice.message.content, "tool_calls": None}
        if not choice.message.tool_calls
        else {"content": choice.message.content,
              "tool_calls": [tc.model_dump() for tc in choice.message.tool_calls]}
    )
    return {"messages": [ai_msg]}


async def tool_node(state: AnalysisState) -> dict:
    """执行上一条 AIMessage 的全部 tool_calls，结果作为 ToolMessage 回填；轮次 +1。"""
    last = state["messages"][-1]
    results = []
    for call in last.tool_calls or []:
        fn = TOOL_REGISTRY.get(call["name"])
        try:
            if fn is None:
                output = f"[50002] 未知工具：{call['name']}"
            else:
                output = await fn(state, **call["args"])
        except BizError as e:
            output = f"工具执行被拒：[{e.code}] {e.message}"  # 拒绝原因回传 Agent 供修正
        except Exception as e:  # noqa: BLE001 —— 工具失败是可回传的业务态
            log.warning("tool_failed", tool=call["name"], error=str(e))
            output = f"工具执行异常：{e}"
        results.append(ToolMessage(tool_call_id=call["id"], content=str(output)[:4000]))
    return {"messages": results, "tool_rounds": state["tool_rounds"] + 1}


async def output_node(state: AnalysisState) -> dict:
    """收敛（或超轮次强制收敛）→ 六段结构化输出。"""
    if state["tool_rounds"] >= get_config().max_tool_rounds:
        state["messages"].append(SystemMessage(
            content="已达工具轮次上限，请基于已收集的证据直接输出最终结论，不再调用工具。"
        ))
    result = await generate_structured_output(state)  # AGENT-7
    return {"final_result": result}


def route_after_agent(state: AnalysisState) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None) and state["tool_rounds"] < get_config().max_tool_rounds:
        return "tools"
    return "output"


def build_graph() -> CompiledStateGraph:
    g = StateGraph(AnalysisState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tool_node)
    g.add_node("output", output_node)
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", route_after_agent, {"tools": "tools", "output": "output"})
    g.add_edge("tools", "agent")  # 工具结果回填后回到 agent
    g.add_edge("output", END)
    return g.compile()


async def execute_analysis(task: AnalysisTask) -> Any:
    """任务执行总入口（task_service.run_task 调用）：拼上下文 → 驱动图 →
    过程事件推送/落库（AGENT-9）→ 结果落库（RES-1）→ 导出兜底 → 摘要检查（CTX-1）。"""
    cfg = get_config()
    cid, tid = task.conversation_id, task.id
    state0 = await build_initial_state(task)
    graph = build_graph()

    assistant_msg_id: int | None = None
    text_buffer: list[str] = []

    async def _ensure_assistant_msg() -> int:
        nonlocal assistant_msg_id
        if assistant_msg_id is None:
            async with new_session() as session, session.begin():
                msg = await message_service.append_message(
                    session, cid, "assistant", "text", "", task_id=tid
                )
                assistant_msg_id = msg.id
        return assistant_msg_id

    async def _push_step(step: str | None) -> None:
        await MANAGER.broadcast(cid, wsmsg.msg_task_status(tid, "running", step))

    final_state: dict | None = None
    # 非流式逐步驱动（node 粒度），工具事件在 tool_node 外层包装推送
    state: AnalysisState = dict(state0)  # type: ignore[assignment]
    while True:
        # ---- agent 节点 ----
        await _push_step("planning" if state["tool_rounds"] == 0 else "querying")
        delta = await agent_node(state)
        ai_msg = delta["messages"][0]
        state["messages"] = state["messages"] + delta["messages"]
        if ai_msg.content:  # 文本增量（节点粒度推送 + 落库）
            mid = await _ensure_assistant_msg()
            text_buffer.append(str(ai_msg.content))
            await MANAGER.broadcast(cid, wsmsg.msg_message_delta(tid, mid, str(ai_msg.content)))

        if route_after_agent(state) != "tools":
            break
        # ---- tools 节点 ----
        last = state["messages"][-1]
        for call in last.tool_calls or []:
            await MANAGER.broadcast(cid, wsmsg.msg_tool_start(
                tid, call["name"], str(call.get("args", {}))[:200]))
            async with new_session() as session, session.begin():
                tmsg = await message_service.append_message(
                    session, cid, "tool", "tool_call", str(call.get("args", {}))[:2000],
                    tool_name=call["name"], tool_status="running", task_id=tid,
                )
                tool_msg_id = tmsg.id
            fn = TOOL_REGISTRY.get(call["name"])
            try:
                output = await fn(state, **call["args"]) if fn else f"[50002] 未知工具：{call['name']}"
                status = "success"
            except Exception as e:  # noqa: BLE001 —— 工具失败回传
                output, status = f"工具执行异常：{e}", "failed"
            await MANAGER.broadcast(cid, wsmsg.msg_tool_finish(
                tid, call["name"], status, str(output)[:500]))
            async with new_session() as session, session.begin():
                await message_service.update_message_content(
                    session, tool_msg_id, str(output)[:2000], tool_status=status)
            state["messages"] = state["messages"] + [
                ToolMessage(tool_call_id=call["id"], content=str(output)[:4000])
            ]
        state["tool_rounds"] += 1
        if state["tool_rounds"] >= cfg.max_tool_rounds:
            state["messages"].append(SystemMessage(
                content="已达工具轮次上限，请基于已收集的证据直接输出最终结论，不再调用工具。"))

    # ---- output 节点 ----
    await _push_step("summarizing")
    out_delta = await output_node(state)
    final_result = out_delta["final_result"]
    final_state = {"final_result": final_result}

    # 终态回填 assistant 全文
    if assistant_msg_id is not None and text_buffer:
        async with new_session() as session, session.begin():
            await message_service.update_message_content(
                session, assistant_msg_id, "\n".join(text_buffer))
    # 结果落库（RES-1，含 result_ready 推送）
    async with new_session() as session, session.begin():
        await result_service.save_result(session, task, final_result)
    # 导出兜底（AGENT-6 产物幂等）
    async with new_session() as session:
        try:
            await result_service.ensure_export_file(session, task.user_id, tid)
        except Exception as e:  # noqa: BLE001 —— 导出失败不阻塞任务成功
            log.warning("export_fallback_failed", task_id=tid, error=str(e))
    # 摘要压缩检查（CTX-1）
    async with new_session() as session:
        if await summary_service.check_compaction_needed(session, cid):
            await summary_service.summarize_range(session, cid)
    return final_result
