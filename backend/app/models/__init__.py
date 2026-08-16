"""SQLAlchemy ORM 模型层：10 张系统表的模型汇总导出。"""

from app.models.attachment import Attachment
from app.models.config import SystemConfigModel
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.result import AnalysisResult
from app.models.summary import ContextSummary
from app.models.task import AnalysisTask
from app.models.task_log import TaskLog
from app.models.user import User
from app.models.ws_token import WsToken

__all__ = [
    "User",
    "Conversation",
    "Message",
    "Attachment",
    "AnalysisTask",
    "AnalysisResult",
    "ContextSummary",
    "WsToken",
    "SystemConfigModel",
    "TaskLog",
]

# 供 Alembic metadata 使用（Base.metadata 已随各模块 import 注册全部表）。
ALL_MODELS = [
    User,
    Conversation,
    Message,
    Attachment,
    AnalysisTask,
    AnalysisResult,
    ContextSummary,
    WsToken,
    SystemConfigModel,
    TaskLog,
]
