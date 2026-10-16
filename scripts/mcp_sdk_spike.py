#!/usr/bin/env python3
"""M0.4 MCP SDK 兼容 spike：用官方 mcp SDK 客户端经 stdio 拉起 domimap 自研 stdlib 服务器，
走 initialize → list_tools → call_tool 全链路。证明 SDK↔自研服务端协议路径可行（M2 迁移评估依据）。

用法（在装了 domimap[mcp] 的解释器里）：python3 scripts/mcp_sdk_spike.py <graph.json>
未安装 mcp 包时以退出码 3 提示（CI 不装 extra，不视为失败）。
"""
import asyncio
import os
import sys

async def main(graph):
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        print("[spike] mcp SDK 未安装（可选 extra：pip install 'domimap[mcp]'）")
        return 3
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    params = StdioServerParameters(
        command=sys.executable, cwd=root,
        args=["-B", "-m", "domimap", "serve", "-g", os.path.abspath(graph)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            info = init.server_info  # SDK 2.x snake_case
            print("[spike] initialize ok: server=%s/%s protocol=%s" %
                  (info.name, info.version, init.protocol_version))
            tools = await session.list_tools()
            print("[spike] tools:", sorted(t.name for t in tools.tools))
            res = await session.call_tool("kg_explore", {"query": "price_version"})
            text = res.content[0].text if res.content else ""
            assert "price_version" in text, text[:200]
            print("[spike] kg_explore 命中 price_version：SDK 客户端 ↔ stdlib 服务端 全链路 OK")
            return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "out/mini/graph.json")))
