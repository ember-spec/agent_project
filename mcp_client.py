"""
MCP 客户端封装

通过 asyncio 子进程 + 原始 JSON-RPC 与 MCP 服务通信，
不依赖 MCP SDK 的传输层（避免 Windows 兼容问题）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import create_model


class JsonRpcClient:
    """基于 asyncio 子进程的 JSON-RPC 客户端"""

    def __init__(self, command: str, args: list[str]):
        self.command = command
        self.args = args
        self._proc = None
        self._req_id = 0
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── 公开方法 ──────────────────────────────────

    def connect(self):
        """启动子进程并完成 MCP 初始化握手"""
        self._run_async(self._do_connect())

    def close(self):
        """关闭子进程"""
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
            self._proc = None
        if self._loop and not self._loop.is_closed():
            self._loop.stop()
            self._loop.close()

    def list_tools(self) -> list[dict]:
        """调用 tools/list，返回工具定义列表"""
        result = self._run_async(self._request("tools/list", {}))
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> str:
        """调用工具，返回文本结果"""
        result = self._run_async(self._request("tools/call", {
            "name": name,
            "arguments": arguments,
        }))
        content = result.get("content", [])
        parts = []
        for c in content:
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            else:
                parts.append(str(c))
        return "\n".join(parts)

    # ── 事件循环 ──────────────────────────────────

    def _ensure_loop(self):
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

    def _run_async(self, coro):
        self._ensure_loop()
        return self._loop.run_until_complete(coro)

    # ── 子进程与 JSON-RPC ─────────────────────────

    async def _do_connect(self):
        """启动子进程并完成 initialize 握手"""
        self._proc = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # initialize
        init_result = await self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "agent-py", "version": "1.0"},
        })
        if "serverInfo" not in init_result:
            raise RuntimeError(f"MCP initialize 失败: {init_result}")

        # initialized 通知（无响应）
        await self._notify("notifications/initialized")

    async def _request(self, method: str, params: dict) -> dict:
        """发送 JSON-RPC 请求并等待响应"""
        self._req_id += 1
        msg = json.dumps({
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
            "params": params,
        })
        await self._send(msg)

        resp = await self._recv()
        if "error" in resp:
            err = resp["error"]
            raise RuntimeError(f"MCP 调用失败 [{method}]: {err.get('message', err)}")
        return resp.get("result", {})

    async def _notify(self, method: str):
        """发送 JSON-RPC 通知（无响应）"""
        msg = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
        })
        await self._send(msg)

    async def _send(self, msg: str):
        """写入一行 JSON 到子进程 stdin"""
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("子进程未启动")
        self._proc.stdin.write((msg + "\n").encode("utf-8"))
        await self._proc.stdin.drain()

    async def _recv(self) -> dict:
        """从子进程 stdout 读取一行 JSON"""
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("子进程未启动")
        line = await asyncio.wait_for(
            self._proc.stdout.readline(),
            timeout=30,
        )
        if not line:
            # 进程可能已退出
            err = self._proc.stderr.read()
            raise ConnectionError(
                f"MCP 子进程连接断开\nstderr: {err.decode() if isinstance(err, bytes) else err}"
            )
        return json.loads(line.decode("utf-8").strip())


class McpClient:
    """高层封装：连接 MCP 服务并返回 LangChain 工具列表"""

    def __init__(
        self,
        command: str = "python",
        args: list[str] | None = None,
        url: str | None = None,
    ):
        self.command = command
        self.args = args or []
        self.url = url
        self._rpc: JsonRpcClient | None = None
        self._tools: list[StructuredTool] | None = None

    def get_tools(self) -> list[StructuredTool]:
        if self._tools is not None:
            return self._tools

        if self.url:
            # 远程 MCP 服务走 SSE（仅当用户明确传 url 时）
            self._tools = self._connect_sse()
        else:
            # 本地服务走 JSON-RPC 子进程
            self._rpc = JsonRpcClient(self.command, self.args)
            self._rpc.connect()
            self._tools = self._build_tools()

        return self._tools

    def close(self):
        if self._rpc:
            self._rpc.close()

    # ── 本地模式 ──────────────────────────────────

    def _build_tools(self) -> list[StructuredTool]:
        """从 MCP 服务获取工具列表，转为 LangChain 工具"""
        raw_tools = self._rpc.list_tools()

        tools = []
        for t in raw_tools:
            name = t["name"]
            desc = t.get("description", "")
            schema = t.get("inputSchema", {})
            args_model = _schema_to_pydantic(name, schema)

            def make_tool(n: str, d: str, rpc: JsonRpcClient):
                def sync_fn(**kwargs: Any) -> str:
                    return rpc.call_tool(n, kwargs)
                return StructuredTool.from_function(
                    name=n,
                    description=d,
                    func=sync_fn,
                    args_schema=args_model,
                )

            tools.append(make_tool(name, desc, self._rpc))

        return tools

    # ── 远程 SSE 模式 ─────────────────────────────
    # （与本地模式独立，走 MCP SDK 传输层）

    def _connect_sse(self) -> list[StructuredTool]:
        import httpx

        # 通过 HTTP 获取工具列表（简化版，完整 SSE 涉及事件流）
        # 生产环境建议使用 MCP SDK 的 sse_client
        raise NotImplementedError(
            "远程 SSE 模式请使用 MCP SDK 直接连接:\n"
            f"  from mcp.client.sse import sse_client\n"
            f"  read, write = await sse_client(url='{self.url}')"
        )


# ── Schema 转换 ─────────────────────────────────

def _schema_to_pydantic(name: str, schema: dict) -> type:
    import typing

    TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    fields = {}
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    for field_name, prop in properties.items():
        json_type = prop.get("type", "string")
        py_type = TYPE_MAP.get(json_type, str)
        if field_name in required:
            fields[field_name] = (py_type, ...)
        else:
            fields[field_name] = (typing.Optional[py_type], None)

    return create_model(f"{name}Args", **fields)