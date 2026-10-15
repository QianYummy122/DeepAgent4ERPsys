"""验证 create_main_agent 的 9 个初始化阶段能否走通（不调用大模型）。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> int:
    # 1. MongoDB 可用性
    from agent.config import check_mongodb

    ok, msg = check_mongodb()
    print(f"[MongoDB] ok={ok} {msg.splitlines()[0]}")
    if not ok:
        return 1

    # 2. 构建 Agent 图
    from agent.main_agent import create_main_agent

    print("\n[Agent] 开始构建 ...")
    graph = await create_main_agent()
    print("[Agent] 构建成功")

    # 3. 检查子智能体与工具装配
    try:
        nodes = sorted(graph.get_graph().nodes.keys())
        print(f"[Graph] 节点数={len(nodes)}")
        print(f"[Graph] 节点={nodes[:40]}")
    except Exception as exc:
        print(f"[Graph] 读取图结构失败: {exc}")

    # 4. 检查 checkpointer 与 store
    print(f"[Graph] checkpointer={'有' if getattr(graph, 'checkpointer', None) else '无'}")
    print(f"[Graph] store={'有' if getattr(graph, 'store', None) else '无'}")

    print("\n✅ Agent 图构建链路验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
