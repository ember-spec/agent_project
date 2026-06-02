"""
Agent 主入口

支持两种工具获取方式:
  1. LOCAL  — 直接从 tools/ 目录 import（默认，不依赖外部服务）
  2. MCP    — 通过 MCP 协议连接服务获取工具（支持 stdio / SSE）
"""

import os
import sys

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, ToolMessage

load_dotenv()

# =========================================
# 配置：切换工具来源
# =========================================
TOOL_SOURCE = os.getenv("TOOL_SOURCE", "LOCAL")  # LOCAL | MCP

if TOOL_SOURCE == "MCP":
    # ── MCP 模式：连接 MCP 服务获取工具 ──
    from mcp_client import McpClient

    # 连接本地 stdio 服务（默认）
    client = McpClient(
        command=sys.executable,
        args=[os.path.join(os.path.dirname(__file__), "mcp_server.py")],
    )
    # 或连接远程 SSE 服务（把下面注释打开即可）
    # client = McpClient(url="http://127.0.0.1:8000/sse")

    tools = client.get_tools()
    print(f"✅ 从 MCP 服务获取了 {len(tools)} 个工具", file=sys.stderr)
    for t in tools:
        print(f"   - {t.name}: {t.description}", file=sys.stderr)
else:
    # ── LOCAL 模式：直接从 tools/ 目录 import ──
    from tools import get_all_tools

    tools = get_all_tools()
    print(f"✅ 从 tools/ 目录加载了 {len(tools)} 个工具", file=sys.stderr)

# =========================================
# LLM 初始化
# =========================================
llm = ChatOpenAI(
    model="glm-4-air",
    api_key=os.getenv("ZHIPUAI_API_KEY"),
    base_url="https://open.bigmodel.cn/api/paas/v4/",
    temperature=0,
).bind_tools(tools)
tool_map = {tool.name: tool for tool in tools}

# =========================================
# 对话循环
# =========================================
while True:
    try:
        content = input("\n>>> ")
    except (EOFError, KeyboardInterrupt):
        break
    if not content:
        continue
    if content.strip().lower() in ("exit", "quit", "q"):
        break

    messages = [HumanMessage(content=content)]

    # 第一轮：LLM 决定是否调工具
    response = llm.invoke(messages)

    # 执行工具调用
    for tool_call in response.tool_calls:
        tool_name = tool_call["name"]
        tool_fn = tool_map.get(tool_name)
        if tool_fn is None:
            print(f"⚠️ 未知工具: {tool_name}")
            continue

        print(f"✅ 调用工具: {tool_name}({tool_call['args']})")
        result = tool_fn.invoke(tool_call["args"])
        print(f"✅ 工具返回: {result}")

        messages.append(response)
        messages.append(ToolMessage(tool_call_id=tool_call["id"], content=result))

    # 第二轮：LLM 综合结果回答
    final = llm.invoke(messages)

    print(f"\n🤖 {final.content}")