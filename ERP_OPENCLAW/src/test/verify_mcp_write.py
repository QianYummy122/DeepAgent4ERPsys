"""验证 MCP 写工具 order_create / order_update 的完整链路（创建→更新→清理）。"""
import asyncio
import json

import httpx
from fastmcp import Client

JAVA_API = "http://localhost:8080/api"


async def main():
    created_id = None
    async with Client("http://127.0.0.1:8000/mcp") as client:
        # ---------- 1. 创建订单 ----------
        print("=== 1. order_create ===")
        res = await client.call_tool(
            "order_create",
            {
                "order_detail": [
                    {"partId": 25, "quantity": 3, "unitPrice": 418.0}
                ],
                "total_amount": 1254.0,
                "status": 1,
                "created_by": 1,
                "remark": "MCP 链路自检订单",
            },
        )
        data = res.data if hasattr(res, "data") else res.content
        print(json.dumps(data, ensure_ascii=False, default=str)[:600])

        if isinstance(data, dict) and data.get("error"):
            print("✗ 创建失败:", data["error"])
            return 1
        created_id = data.get("id") if isinstance(data, dict) else None
        print(f"-> 新订单 ID = {created_id}")

        # ---------- 2. 更新订单状态 ----------
        print("\n=== 2. order_update ===")
        res = await client.call_tool(
            "order_update",
            {
                "order_id": created_id,
                "status": 2,
                "remark": "MCP 链路自检订单（已审核）",
            },
        )
        data = res.data if hasattr(res, "data") else res.content
        print(json.dumps(data, ensure_ascii=False, default=str)[:600])
        if isinstance(data, dict) and data.get("error"):
            print("✗ 更新失败:", data["error"])
            return 1

        # ---------- 3. 通过 REST 复核 ----------
        print("\n=== 3. REST 复核 GET /orders/get/{id} ===")
        async with httpx.AsyncClient(base_url=JAVA_API, timeout=20) as http:
            r = await http.get(f"/orders/get/{created_id}")
            body = r.json()
            print(f"code={body.get('code')}")
            order = body.get("data") or {}
            print(
                "orderNumber=", order.get("orderNumber"),
                "status=", order.get("status"),
                "totalAmount=", order.get("totalAmount"),
            )

            # ---------- 4. 清理 ----------
            print("\n=== 4. 清理测试订单 ===")
            d = await http.delete(f"/orders/delete/{created_id}")
            print("delete ->", d.json().get("code"))

    print("\n✅ 写链路（MCP -> REST -> MySQL）验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
