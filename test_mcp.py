"""用 MCP Client SDK 测试 MCP 服务"""
import asyncio
import os
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    # 自动定位到 mcp_server.py（与 test_mcp.py 同目录）
    server_script = os.path.join(os.path.dirname(__file__), "mcp_server.py")
    if not os.path.exists(server_script):
        print(f"❌ 找不到 mcp_server.py: {server_script}", file=sys.stderr)
        sys.exit(1)

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[server_script],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 列出工具
            tools = await session.list_tools()
            print("===== tools/list =====")
            for t in tools.tools:
                print(f"  - {t.name}: {t.description}")
                print(f"    inputSchema: {t.inputSchema}")

            # 调用 get_weather
            res = await session.call_tool("get_weather", {"city": "北京"})
            print("\n===== tools/call (get_weather) =====")
            for c in res.content:
                print(f"  {c.text}")

            # 调用 add
            res = await session.call_tool("add", {"a": 3, "b": 5})
            print("\n===== tools/call (add) =====")
            for c in res.content:
                print(f"  {c.text}")


if __name__ == "__main__":
    asyncio.run(main())