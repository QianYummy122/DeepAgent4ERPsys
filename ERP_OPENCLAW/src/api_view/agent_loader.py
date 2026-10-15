"""
Agent 加载器

使用单例模式加载和管理 DeepAgent 实例。
Agent 实例通过 agent.main_agent.get_agent_async() 懒加载，
内部已集成 MongoDBSaver checkpointer 实现对话状态持久化。
"""

import sys
from pathlib import Path
from typing import Optional, List, Dict, Any
import uuid
from datetime import datetime

# 将项目根目录添加到 Python 路径
PROJECT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from pymongo import MongoClient

# 导入配置
from api_view.web_config import (
    MONGODB_URI,
    MONGODB_DB_NAME,
    MONGODB_CHECKPOINT_COLLECTION,
)


class AgentLoader:
    """
    Agent 加载器单例类

    负责管理 Agent 生命周期、MongoDB 连接和会话相关操作。
    Agent 实例通过 main_agent.get_agent_async() 懒加载，
    checkpointer 由 main_agent 内部统一管理（MongoDBSaver）。
    """

    # 类级别的单例实例
    _instance: Optional['AgentLoader'] = None
    # MongoDB 客户端（用于展示消息存取、会话管理等直接 DB 操作）
    _mongodb_client: Optional[MongoClient] = None
    # 是否已初始化
    _initialized: bool = False
    # Agent 实例
    _agent = None

    def __new__(cls):
        """确保单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def initialize(self):
        """
        初始化 MongoDB 客户端并懒加载 Agent 实例。

        Agent 通过 main_agent.get_agent_async() 获取，
        内部已集成 MongoDBSaver checkpointer，无需在此重复创建。

        Returns:
            Agent 实例
        """
        if self._initialized and self._agent is not None:
            return self._agent

        print("[AgentLoader] 开始初始化...")

        try:
            # 创建 MongoDB 客户端（用于展示消息存取、会话管理等直接 DB 操作）
            self._mongodb_client = MongoClient(MONGODB_URI)

            # 通过 main_agent 的懒加载方法获取 Agent（内部已集成 MongoDBSaver checkpointer）
            from agent.main_agent import get_agent_async
            self._agent = await get_agent_async()

            self._initialized = True
            print("[AgentLoader] 初始化完成")
        except Exception:
            # Agent 创建失败时清理 MongoClient，防止重试时连接泄漏
            if self._mongodb_client is not None:
                self._mongodb_client.close()
                self._mongodb_client = None
            raise

        return self._agent

    @property
    def agent(self):
        """
        获取 Agent 实例

        Returns:
            Agent 实例

        Raises:
            RuntimeError: 如果 Agent 未初始化
        """
        if self._agent is None:
            raise RuntimeError("Agent 未初始化，请先调用 initialize() 方法")
        return self._agent

    # checkpointer 已由 main_agent 内部通过 MongoDBSaver 统一管理，
    # 不再在 AgentLoader 中重复创建。Agent 的 astream/aget_state 等
    # 方法直接使用其内部 checkpointer 进行对话状态持久化。

    def create_config(
        self,
        thread_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        创建 Agent 调用配置

        Args:
            thread_id: 会话 ID，为空则自动生成
            user_id: 用户 ID，用于记忆隔离和上下文注入。
                     为空时使用 'default_user'，多用户场景必须传入。
            **kwargs: 其他可配置的参数

        Returns:
            Dict: Agent 配置字典
        """
        return {
            "configurable": {
                "thread_id": thread_id or str(uuid.uuid4()),
                "user_id": user_id or "laoxiao",
                **kwargs
            }
        }

    async def get_state_history(
        self,
        thread_id: str,
        limit: int = 50
    ) -> List[Any]:
        """
        获取会话的历史状态

        Args:
            thread_id: 会话 ID
            limit: 返回的最大状态数量

        Returns:
            List[StateSnapshot]: 状态快照列表
        """
        config = self.create_config(thread_id)
        states = []

        # 使用 agent.get_state_history 获取历史
        async for state in self.agent.aget_state_history(config):
            states.append(state)
            if len(states) >= limit:
                break

        return states

    async def get_current_messages(self, thread_id: str) -> List[Dict[str, Any]]:
        """
        获取当前会话的消息列表

        Args:
            thread_id: 会话 ID

        Returns:
            List[Dict]: 消息列表
        """
        config = self.create_config(thread_id)

        try:
            state = await self.agent.aget_state(config)
            if state and state.values:
                return state.values.get("messages", [])
        except Exception as e:
            print(f"[AgentLoader] 获取消息失败: {e}")

        return []

    def get_all_thread_ids(self) -> List[str]:
        """
        从 MongoDB 获取所有会话的 thread_id

        Returns:
            List[str]: 所有会话 ID 列表
        """
        if self._mongodb_client is None:
            return []

        db = self._mongodb_client[MONGODB_DB_NAME]
        collection = db[MONGODB_CHECKPOINT_COLLECTION]

        # 获取所有唯一的 thread_id（MongoDB 文档中 thread_id 直接存储在顶层字段）
        thread_ids = collection.distinct("thread_id")

        # 过滤掉空值和通配符
        return [tid for tid in thread_ids if tid and tid != "*" and tid != "" and tid is not None]

    def get_session_updated_at(self, thread_id: str) -> datetime:
        """
        获取会话的最后更新时间

        Args:
            thread_id: 会话 ID

        Returns:
            datetime: 最后更新时间
        """
        if self._mongodb_client is None:
            return datetime.now()

        db = self._mongodb_client[MONGODB_DB_NAME]
        collection = db[MONGODB_CHECKPOINT_COLLECTION]

        try:
            # 获取该 thread_id 的最新文档（按 _id 倒序，_id 包含时间戳）
            latest_doc = collection.find_one(
                {"thread_id": thread_id},
                sort=[("_id", -1)]
            )

            if latest_doc:
                # 从 _id 中提取时间戳（MongoDB _id 的前4字节是时间戳）
                if "_id" in latest_doc and hasattr(latest_doc["_id"], 'generation_time'):
                    return latest_doc["_id"].generation_time
                # 如果没有 generation_time 属性，尝试其他方式
                elif "_id" in latest_doc:
                    import bson
                    if isinstance(latest_doc["_id"], bson.objectid.ObjectId):
                        return latest_doc["_id"].generation_time

            return datetime.now()
        except Exception as e:
            print(f"[AgentLoader] 获取会话时间失败: {e}")
            return datetime.now()

    async def delete_session(self, thread_id: str) -> bool:
        """
        删除会话（删除该 thread_id 下的所有 checkpoint）

        Args:
            thread_id: 会话 ID

        Returns:
            bool: 是否删除成功
        """
        if self._mongodb_client is None:
            return False

        db = self._mongodb_client[MONGODB_DB_NAME]
        collection = db[MONGODB_CHECKPOINT_COLLECTION]

        try:
            # 删除该 thread_id 的所有 checkpoint
            result = collection.delete_many({
                "thread_id": thread_id
            })
            # 同步删除展示消息
            display_collection = db["session_display_messages"]
            display_result = display_collection.delete_many({"thread_id": thread_id})
            print(f"[AgentLoader] 已删除会话 {thread_id}，checkpoint {result.deleted_count} 条，展示消息 {display_result.deleted_count} 条")
            return True
        except Exception as e:
            print(f"[AgentLoader] 删除会话失败: {e}")
            return False


    # ============================================================
    # 完整展示消息存取（包含子代理消息，解决 checkpoint 丢失子代理消息的问题）
    # ============================================================

    # 单字段最大字符数（约 500KB），防止单条消息超过 MongoDB 16MB 文档限制
    _MAX_FIELD_LENGTH = 500_000

    @classmethod
    def _truncate_message_fields(cls, msg: Dict[str, Any]) -> Dict[str, Any]:
        """截断消息中的超长文本字段，避免单文档超过 MongoDB 16MB 限制"""
        for field in ("text", "content", "args"):
            if field in msg and isinstance(msg[field], str) and len(msg[field]) > cls._MAX_FIELD_LENGTH:
                msg[field] = msg[field][:cls._MAX_FIELD_LENGTH] + "\n\n...(内容过长已截断)"
        return msg

    async def save_display_messages(self, thread_id: str, messages: List[Dict[str, Any]]) -> bool:
        """
        将完整的展示消息逐条存入 MongoDB

        改为逐条存储（每条消息一个 MongoDB 文档），彻底解决以下问题：
        1. 单文档 16MB 限制：长对话含大量工具结果时容易超限，导致保存静默失败
        2. 增量更新：后续可扩展为边流式边存储，即使中断也不丢数据

        Args:
            thread_id: 会话 ID
            messages: 完整的展示消息列表

        Returns:
            bool: 是否保存成功
        """
        if self._mongodb_client is None:
            return False

        try:
            db = self._mongodb_client[MONGODB_DB_NAME]
            collection = db["session_display_messages"]

            # 确保索引存在（幂等操作）
            try:
                collection.create_index([("thread_id", 1), ("index", 1)])
            except Exception:
                pass

            # 删除该线程的旧消息
            collection.delete_many({"thread_id": thread_id})

            # 逐条插入，每条消息独立一个文档
            if messages:
                now = datetime.now()
                docs = []
                for i, msg in enumerate(messages):
                    msg = self._truncate_message_fields(msg)
                    docs.append({
                        "thread_id": thread_id,
                        "index": i,
                        "message": msg,
                        "updated_at": now
                    })
                collection.insert_many(docs)
                print(f"[AgentLoader] 已保存 {len(docs)} 条展示消息，thread_id={thread_id}")

            return True
        except Exception as e:
            print(f"[AgentLoader] 保存展示消息失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def get_display_messages(self, thread_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        从 MongoDB 逐条读取完整的展示消息

        Args:
            thread_id: 会话 ID

        Returns:
            List[Dict] 或 None: 完整的展示消息列表，不存在时返回 None
        """
        if self._mongodb_client is None:
            return None

        try:
            db = self._mongodb_client[MONGODB_DB_NAME]
            collection = db["session_display_messages"]

            cursor = collection.find({"thread_id": thread_id}).sort("index", 1)
            docs = list(cursor)

            if not docs:
                return None

            messages = [doc["message"] for doc in docs]
            print(f"[AgentLoader] 已读取 {len(messages)} 条展示消息，thread_id={thread_id}")
            return messages
        except Exception as e:
            print(f"[AgentLoader] 读取展示消息失败: {e}")
            import traceback
            traceback.print_exc()
            return None


# 全局单例实例
agent_loader = AgentLoader()
