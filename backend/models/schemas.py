"""
Pydantic 数据模型 - 请求/响应 Schema
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ── 对话相关 ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """对话请求"""
    message: str = Field(..., description="用户输入的自然语言消息")
    session_id: Optional[str] = Field(None, description="会话 ID，用于多轮对话")
    model: Optional[str] = Field(None, description="指定模型，默认使用配置中的模型")


class ChatResponse(BaseModel):
    """对话响应"""
    response: str = Field(..., description="Agent 的回复内容")
    session_id: Optional[str] = None
    pending_approval: Optional[Dict[str, Any]] = Field(
        None, description="待确认的操作（如果有）"
    )
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# ── 数据同步相关 ────────────────────────────────────────────

class SyncMode(str, Enum):
    """同步模式"""
    APPEND = "append"      # 追加
    UPSERT = "upsert"      # 更新插入
    REPLACE = "replace"     # 替换（清空后写入）


class SyncAPIRequest(BaseModel):
    """API 同步请求"""
    api_url: str = Field(..., description="API 接口地址")
    target_table: str = Field(..., description="MySQL 目标表名")
    sync_mode: SyncMode = Field(SyncMode.APPEND, description="同步模式")
    headers: Optional[Dict[str, str]] = Field(None, description="HTTP 请求头")
    params: Optional[Dict[str, Any]] = Field(None, description="请求参数")
    pagination: Optional[Dict[str, Any]] = Field(
        None,
        description="分页配置，如 {'page_param': 'page', 'size_param': 'page_size', 'page_size': 100}",
    )


class SyncCSVRequest(BaseModel):
    """CSV 导入请求"""
    file_path: str = Field(..., description="CSV 文件路径")
    target_table: str = Field(..., description="MySQL 目标表名")
    sync_mode: SyncMode = Field(SyncMode.APPEND, description="同步模式")
    encoding: str = Field("utf-8", description="文件编码")


class SyncResult(BaseModel):
    """同步结果"""
    status: str
    table: Optional[str] = None
    total: int = 0
    inserted: int = 0
    sync_mode: Optional[str] = None
    message: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# ── 定时任务相关 ────────────────────────────────────────────

class TaskCreateRequest(BaseModel):
    """创建定时任务请求"""
    name: str = Field(..., description="任务名称")
    cron_expr: str = Field(..., description="Cron 表达式，如 '0 2 * * *'")
    task_type: str = Field(..., description="任务类型: sync_api | sync_csv | etl")
    params: Dict[str, Any] = Field(..., description="任务参数")


class TaskResponse(BaseModel):
    """任务信息"""
    task_id: str
    name: str
    cron_expr: str
    task_type: str
    params: Dict[str, Any]
    enabled: bool = True
    last_run: Optional[str] = None
    last_status: Optional[str] = None
    created_at: Optional[str] = None


# ── 审批相关 ────────────────────────────────────────────────

class ApprovalAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"


class ApprovalRequest(BaseModel):
    """审批操作请求"""
    approval_id: str = Field(..., description="审批 ID")
    action: ApprovalAction = Field(..., description="审批动作")
    edited_sql: Optional[str] = Field(None, description="编辑后的 SQL（action=edit 时）")


class ApprovalInfo(BaseModel):
    """待审批操作信息"""
    id: str
    operation: str
    sql: str
    estimated_rows: int
    context: Optional[Dict[str, Any]] = None
    status: str
    created_at: str


# ── SQL 执行相关 ────────────────────────────────────────────

class SQLExecuteRequest(BaseModel):
    """SQL 执行请求"""
    sql: str = Field(..., description="要执行的 SQL 语句")
    requires_approval: bool = Field(True, description="是否需要审批")


class SQLValidateResult(BaseModel):
    """SQL 验证结果"""
    is_valid: bool
    is_dangerous: bool = False
    warnings: List[str] = Field(default_factory=list)
    estimated_affected_rows: int = 0
    sql_type: str = ""  # SELECT / INSERT / UPDATE / DELETE / CREATE / DROP / ALTER


# ── 数据血缘相关 ────────────────────────────────────────────

class LineageNode(BaseModel):
    """血缘节点"""
    id: str
    name: str
    type: str  # api / csv / table / query
    label: Optional[str] = None


class LineageEdge(BaseModel):
    """血缘边"""
    source: str
    target: str
    operation: str


class LineageGraph(BaseModel):
    """血缘图"""
    nodes: List[LineageNode] = Field(default_factory=list)
    edges: List[LineageEdge] = Field(default_factory=list)


# ── 配置相关 ────────────────────────────────────────────────

class DatabaseConfig(BaseModel):
    """数据库配置"""
    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str = "root"
    database: str = "datapilot"
    pool_size: int = 10


class LLMConfig(BaseModel):
    """LLM 配置"""
    provider: str = "openai"  # openai / deepseek
    model: str = "gpt-4o-mini"
    api_key: str = ""
    api_base: Optional[str] = None
    temperature: float = 0.1
    max_tokens: int = 4096


# ── 通用响应 ────────────────────────────────────────────────

class APIResponse(BaseModel):
    """通用 API 响应"""
    success: bool
    message: str = ""
    data: Optional[Any] = None
    error: Optional[str] = None
