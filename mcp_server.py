"""
MCP 服务入口

将 tools/ 目录下的所有 LangChain 工具暴露为 MCP 服务，
支持 stdio 和 SSE 两种传输协议。

用法:
  # stdio 模式（默认，适用于 Claude Desktop 集成）
  python mcp_server.py

  # SSE 模式（适用于远程 HTTP 调用）
  python mcp_server.py --transport sse --port 8000
"""

import argparse
import sys

from tools import get_all_tools


def create_mcp_server(host: str = "127.0.0.1", port: int = 8000):
    """创建 FastMCP 服务，注册 tools/ 目录下所有工具"""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "agent-tools",
        instructions="提供天气查询、数学计算等工具",
        host=host,
        port=port,
    )

    # 动态注册 tools/ 下的所有 LangChain 工具
    for langchain_tool in get_all_tools():
        if not langchain_tool.func:
            print(f"⚠️ 工具 {langchain_tool.name} 缺少原始函数，跳过", file=sys.stderr)
            continue

        # 直接注册原始 Python 函数，FastMCP 会自动提取类型注解生成 JSON Schema
        mcp.add_tool(
            fn=langchain_tool.func,
            name=langchain_tool.name,
            description=langchain_tool.description,
        )
        print(f"✅ 注册工具: {langchain_tool.name}", file=sys.stderr)

    return mcp


def main():
    parser = argparse.ArgumentParser(description="Agent MCP 服务")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="传输协议 (默认: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="SSE 监听地址")
    parser.add_argument("--port", type=int, default=8000, help="SSE 监听端口")
    args = parser.parse_args()

    mcp = create_mcp_server(host=args.host, port=args.port)

    if args.transport == "sse":
        print(f"🚀 MCP 服务运行在 http://{args.host}:{args.port}/sse", file=sys.stderr)
        mcp.run(transport="sse")
    else:
        print("🚀 MCP 服务运行在 stdio 模式", file=sys.stderr)
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()