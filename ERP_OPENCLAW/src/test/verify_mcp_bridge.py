"""通过 MCP 客户端逐个验证 ERP 桥接服务的工具，并打印实际回传内容摘要。"""
import asyncio
import json
import sys

from fastmcp import Client


def brief(value, limit=400):
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + f"...(+{len(text)-limit} chars)"


async def main():
    url = "http://127.0.0.1:8000/mcp"
    async with Client(url) as client:
        tools = await client.list_tools()
        print(f"[OK] 连接成功，共 {len(tools)} 个工具:")
        for t in tools:
            print(f"     - {t.name}")
        print("-" * 70)

        cases = [
            ("supplier_query", {"name": "博世"}),
            ("part_query", {"current": 1, "size": 3, "name": "火花塞"}),
            ("part_search", {"name": "火花塞"}),
            ("part_by_supplier", {"supplier_id": 1}),
            ("order_search_details", {"part_name": "火花塞"}),
            ("inventory_warning", {}),
        ]

        failures = []
        for name, args in cases:
            try:
                res = await client.call_tool(name, args)
                data = res.data if hasattr(res, "data") else res.content
                text = brief(data)
                print(f"[{name}] -> {text}")
                if isinstance(data, list) and data and isinstance(data[0], str):
                    failures.append((name, data[0]))
                elif isinstance(data, dict) and "error" in data:
                    failures.append((name, data["error"]))
            except Exception as exc:
                print(f"[{name}] EXCEPTION: {exc}")
                failures.append((name, str(exc)))
            print("-" * 70)

        print("\n===== 失败项汇总 =====")
        if not failures:
            print("无失败项 ✅")
        else:
            for n, e in failures:
                print(f"  ✗ {n}: {e[:200]}")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
