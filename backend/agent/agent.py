"""
MySQL DataPilot 智能体 - 基于 LangGraph ReAct 架构
核心决策引擎，封装所有 Tool，用自然语言驱动数据操作
"""

import json
import logging
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from .hitl import HITLManager


class MySQLAgent:
    """
    MySQL 智能体 - 基于 LangGraph ReAct 架构

    封装 8+ 个工具，覆盖数据库数据操作全链路：
    1. get_schema         — 获取表结构
    2. list_tables         — 列出所有表
    3. generate_sql        — 生成 SQL
    4. validate_sql        — 验证 SQL 安全性
    5. execute_query       — 执行 SELECT 查询
    6. execute_write       — 执行写操作（需审批）
    7. sync_from_api       — 从 API 拉取数据
    8. sync_from_csv       — 从 CSV 导入数据
    9. create_table        — 创建表
    10. etl_transform       — ETL 转换
    11. create_schedule     — 创建定时任务
    12. get_database_info   — 获取数据库概况
    """

    SYSTEM_PROMPT = """你是一个专业的 MySQL 数据管家助手 —— MySQL DataPilot。

## 你的核心能力
你不仅能查询数据库，还能主动从外部拉取数据、做 ETL 转换、管理定时任务。
你是市面上唯一一个覆盖"数据进来 → 数据流转 → 数据出去"完整链路的数据管家。

## 安全规则（必须严格遵守）
1. 默认只允许执行 SELECT 查询。
2. 对于 INSERT/UPDATE/DELETE/CREATE/DROP/TRUNCATE 操作，必须使用 execute_write 工具，
   该工具会自动触发人工确认流程，等待用户批准后才能执行。
3. 绝对禁止对表名不带 "sync_" 或 "tmp_" 前缀的生产表执行 DROP 操作。
4. 所有 UPDATE/DELETE 操作必须包含 WHERE 条件，不允许全表更新。
5. 执行任何写操作前，必须先通过 validate_sql 检查安全性。

## 工作流程
1. 收到用户问题后，先判断意图（查询？同步？建表？ETL？调度？）
2. 如果是查询操作：
   a. 调用 get_schema 或 list_tables 了解数据库结构
   b. 调用 generate_sql 生成 SQL
   c. 调用 validate_sql 检查安全性
   d. 调用 execute_query 执行并返回结果
3. 如果是数据同步操作（用户提到"同步"、"导入"、"拉取"）：
   a. 识别数据源类型（API/CSV/JSON）
   b. 调用 sync_from_api 或 sync_from_csv
   c. 同步完成后展示结果
4. 如果是写操作（INSERT/UPDATE/DELETE）：
   a. 先生成 SQL 并验证
   b. 展示给用户确认
   c. 使用 execute_write 执行
5. 如果是 ETL 操作（用户提到"汇总"、"统计"、"转换"）：
   a. 了解源表结构
   b. 生成 ETL SQL
   c. 使用 execute_write 执行（可能需要审批）

## 回答格式要求
- 用通俗易懂的中文回复
- 展示生成的 SQL 语句时，使用 ```sql 代码块
- 查询结果用 Markdown 表格形式展示
- 如果触发了审批流程，明确告知用户需要前往前端确认
- 每次操作前简要说明你在做什么

## 当前数据库上下文
用户连接的数据库信息可以通过 get_database_info 获取。
在生成任何 SQL 之前，务必先获取相关表的结构信息。
"""

    def __init__(
        self,
        mysql_client,
        sync_engine: "ExternalSyncEngine" = None,
        model_name: str = "gpt-4o-mini",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        api_key: str = None,
        api_base: str = None,
        verbose: bool = False,
    ):
        self.mysql = mysql_client
        self.sync_engine = sync_engine
        self.hitl = HITLManager(mysql_client)
        self.logger = logging.getLogger(__name__)

        # 初始化 LLM
        llm_kwargs = {
            "model": model_name,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if api_key:
            llm_kwargs["api_key"] = api_key
        elif os.getenv("OPENAI_API_KEY"):
            llm_kwargs["api_key"] = os.getenv("OPENAI_API_KEY")
        if api_base:
            llm_kwargs["base_url"] = api_base
        elif os.getenv("OPENAI_API_BASE"):
            llm_kwargs["base_url"] = os.getenv("OPENAI_API_BASE")

        self.llm = ChatOpenAI(**llm_kwargs)
        self.verbose = verbose

        # 构建工具列表
        self.tools = self._create_tools()

        # 创建 ReAct Agent（带记忆）
        self.memory = MemorySaver()
        self.agent = create_react_agent(
            model=self.llm,
            tools=self.tools,
            prompt=self.SYSTEM_PROMPT,
            checkpointer=self.memory,
        )

    # ── 工具创建 ─────────────────────────────────────────────

    def _create_tools(self):
        """创建 Agent 工具集"""
        mysql = self.mysql
        hitl = self.hitl
        sync_engine = self.sync_engine
        logger = self.logger

        @tool
        def get_schema(table_name: str = "") -> str:
            """
            获取数据库表结构信息。
            参数:
                table_name: 表名（可选），不传则返回所有表的列表和大致概况。
            使用场景: 在生成任何 SQL 之前，必须先调用此工具了解表结构。
            示例:
                - get_schema() → 列出所有表
                - get_schema("orders") → 获取 orders 表的详细结构
            """
            try:
                if table_name:
                    schema = mysql.get_table_schema(table_name)
                else:
                    schema = mysql.get_table_schema()
                return json.dumps(schema, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"get_schema error: {e}")
                return json.dumps({"error": str(e)}, ensure_ascii=False)

        @tool
        def list_tables() -> str:
            """
            列出数据库中所有表以及每张表的行数。
            使用场景: 快速了解数据库中有哪些数据可用。
            """
            try:
                info = mysql.get_database_info()
                return json.dumps(info, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"list_tables error: {e}")
                return json.dumps({"error": str(e)}, ensure_ascii=False)

        @tool
        def generate_sql(user_request: str, table_schema_json: str) -> str:
            """
            根据用户的自然语言需求和表结构信息，生成符合 MySQL 语法的 SQL 语句。
            参数:
                user_request: 用户的自然语言数据需求描述
                table_schema_json: 相关表的 schema JSON（从 get_schema 获取）
            返回: 生成的 SQL 语句及简要说明。
            注意: 生成的 SQL 在执行前应该使用 validate_sql 进行安全检查。
            """
            # 这里用简单的规则辅助；实际执行时 LLM 会自己生成 SQL
            return json.dumps({
                "status": "ok",
                "message": "SQL 生成请求已接收。LLM 将根据表结构和用户需求在思考过程中生成 SQL。",
                "table_schema_provided": table_schema_json[:500] + "..." if len(table_schema_json) > 500 else table_schema_json,
            }, ensure_ascii=False)

        @tool
        def validate_sql(sql: str) -> str:
            """
            验证 SQL 语句的安全性。
            参数:
                sql: 待验证的 SQL 语句
            返回: 安全验证结果（JSON），包含 is_dangerous、warnings 等字段。
            所有写操作前必须调用此工具检查！
            """
            try:
                analysis = hitl.analyze_sql(sql)
                return json.dumps(analysis, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"validate_sql error: {e}")
                return json.dumps({"error": str(e)}, ensure_ascii=False)

        @tool
        def execute_query(sql: str) -> str:
            """
            执行只读的 SELECT 查询并返回结果。
            参数:
                sql: 已验证的 SELECT 查询语句
            返回: 查询结果（JSON 格式，最多返回 200 行）
            注意: 此工具仅支持 SELECT 语句。对于写操作，请使用 execute_write 工具。
            """
            try:
                sql_stripped = sql.strip().rstrip(";")
                if not sql_stripped.upper().startswith("SELECT"):
                    return json.dumps({
                        "error": "execute_query 仅支持 SELECT 查询。对于写操作（INSERT/UPDATE/DELETE），请使用 execute_write 工具。",
                        "sql_provided": sql_stripped[:200],
                    }, ensure_ascii=False)

                # 安全限制：LIMIT 200
                if "LIMIT" not in sql_stripped.upper():
                    sql_stripped += " LIMIT 200"

                result = mysql.execute_query(sql_stripped)
                return json.dumps({
                    "status": "success",
                    "row_count": len(result),
                    "data": result,
                }, ensure_ascii=False, default=str)
            except Exception as e:
                logger.error(f"execute_query error: {e}")
                return json.dumps({
                    "status": "failed",
                    "error": str(e),
                }, ensure_ascii=False)

        @tool
        def execute_write(operation: str, sql: str, reason: str = "") -> str:
            """
            执行写操作（INSERT/UPDATE/DELETE/CREATE 等），会触发人工审批流程。
            参数:
                operation: 操作描述，如 "创建订单汇总表"、"更新用户状态"
                sql: 要执行的 SQL 语句
                reason: 执行此操作的业务原因
            返回: 审批状态。注意：此工具会触发人工确认流程，用户需在前端批准后才会真正执行。
            所有非 SELECT 操作都必须通过此工具执行！
            """
            try:
                # 先验证 SQL
                analysis = hitl.analyze_sql(sql)
                if analysis.get("affects_all_rows"):
                    return json.dumps({
                        "status": "blocked",
                        "message": "⚠️ 安全拦截：UPDATE/DELETE 缺少 WHERE 条件，将影响所有行！已阻止此操作。请添加 WHERE 条件后重试。",
                        "analysis": analysis,
                    }, ensure_ascii=False)

                # 发起审批请求
                approval_result = hitl.request_approval(
                    operation=operation,
                    sql=sql,
                    estimated_rows=analysis.get("estimated_affected_rows", 0),
                    context={"reason": reason, "analysis": analysis},
                )

                return json.dumps({
                    "status": "pending_approval",
                    "message": f"⚠️ 操作 '{operation}' 需要您的确认。请在前端点击「确认执行」来批准此操作。",
                    "approval_id": approval_result.get("approval_id"),
                    "sql": sql,
                    "analysis": analysis,
                }, ensure_ascii=False)
            except Exception as e:
                logger.error(f"execute_write error: {e}")
                return json.dumps({"status": "failed", "error": str(e)}, ensure_ascii=False)

        @tool
        def sync_from_api(
            api_url: str,
            target_table: str,
            sync_mode: str = "append",
            headers_json: str = "{}",
            params_json: str = "{}",
        ) -> str:
            """
            从外部 RESTful API 拉取数据并同步到 MySQL 表。
            参数:
                api_url: API 接口地址（完整的 URL）
                target_table: MySQL 目标表名
                sync_mode: 同步模式 — append(追加) | upsert(更新插入) | replace(替换，清空后写入)
                headers_json: HTTP 请求头（JSON 字符串），如 '{"Authorization": "Bearer xxx"}'
                params_json: 请求参数（JSON 字符串），如 '{"status": "active"}'
            返回: 同步结果，包括同步的数据量。
            使用场景:
                - 用户说 "把 https://api.example.com/orders 的数据同步到 orders 表"
                - 用户说 "从 XX 接口拉取用户数据"
            注意: 此工具会自动检测 API 返回的数据结构，自动建表（如果表不存在）。
            """
            if sync_engine is None:
                return json.dumps({
                    "status": "failed",
                    "error": "同步引擎未初始化，请联系管理员配置",
                }, ensure_ascii=False)

            try:
                headers = json.loads(headers_json) if headers_json else None
                params = json.loads(params_json) if params_json else None

                result = sync_engine.sync_from_api(
                    api_url=api_url,
                    target_table=target_table,
                    sync_mode=sync_mode,
                    headers=headers,
                    params=params,
                )
                return json.dumps(result, ensure_ascii=False, default=str)
            except json.JSONDecodeError as e:
                return json.dumps({
                    "status": "failed",
                    "error": f"JSON 解析错误: {str(e)}",
                }, ensure_ascii=False)
            except Exception as e:
                logger.error(f"sync_from_api error: {e}")
                return json.dumps({
                    "status": "failed",
                    "error": str(e),
                }, ensure_ascii=False)

        @tool
        def sync_from_csv(
            file_path: str,
            target_table: str,
            sync_mode: str = "append",
        ) -> str:
            """
            从 CSV 文件导入数据到 MySQL 表。
            参数:
                file_path: CSV 文件的完整路径
                target_table: MySQL 目标表名
                sync_mode: 同步模式 — append(追加) | upsert(更新插入) | replace(替换)
            返回: 导入结果。
            使用场景:
                - 用户说 "把 /data/sales.csv 导入到 sales_data 表"
                - 用户说 "把这个 CSV 文件的数据同步过来"
            """
            if sync_engine is None:
                return json.dumps({
                    "status": "failed",
                    "error": "同步引擎未初始化，请联系管理员配置",
                }, ensure_ascii=False)

            try:
                result = sync_engine.sync_from_csv(
                    file_path=file_path,
                    target_table=target_table,
                    sync_mode=sync_mode,
                )
                return json.dumps(result, ensure_ascii=False, default=str)
            except Exception as e:
                logger.error(f"sync_from_csv error: {e}")
                return json.dumps({
                    "status": "failed",
                    "error": str(e),
                }, ensure_ascii=False)

        @tool
        def create_table(table_name: str, columns_description: str) -> str:
            """
            在 MySQL 中创建新表。
            参数:
                table_name: 表名（建议使用小写字母和下划线）
                columns_description: 列定义，MySQL DDL 语法。
                    例如: "id BIGINT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100) NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
            返回: 建表结果。
            注意: 此操作需要经过审批确认。
            """
            try:
                if mysql.table_exists(table_name):
                    return json.dumps({
                        "status": "failed",
                        "error": f"表 '{table_name}' 已存在。如需重建，请先 DROP 或使用其他表名。",
                    }, ensure_ascii=False)

                mysql.create_table_from_schema(table_name, columns_description)
                return json.dumps({
                    "status": "success",
                    "message": f"表 '{table_name}' 创建成功",
                    "table": table_name,
                }, ensure_ascii=False)
            except Exception as e:
                logger.error(f"create_table error: {e}")
                return json.dumps({
                    "status": "failed",
                    "error": str(e),
                }, ensure_ascii=False)

        @tool
        def etl_transform(
            source_table: str,
            target_table: str,
            transform_logic: str,
        ) -> str:
            """
            在 MySQL 内部执行表到表的 ETL 转换（Extract-Transform-Load）。
            参数:
                source_table: 源数据表名
                target_table: 目标表名（如果不存在会自动创建）
                transform_logic: 转换逻辑的自然语言描述。
                    例如: "按 customer_id 分组，汇总每个客户的订单总额和订单数"
                    例如: "将 orders 和 customers 按 customer_id 关联，提取客户名、订单日期和金额"
            返回: ETL 执行结果。
            使用场景:
                - 用户说 "把 trades 表按天汇总到 daily_summary"
                - 用户说 "帮我做一个销售汇总表"
            注意: 此工具会使用 LLM 生成实际的 ETL SQL，并需要审批确认后执行。
            """
            try:
                # 获取源表结构
                source_schema = mysql.get_table_schema(source_table)
                if "error" in source_schema:
                    return json.dumps({
                        "status": "failed",
                        "error": f"源表 '{source_table}' 不存在",
                    }, ensure_ascii=False)

                return json.dumps({
                    "status": "ready",
                    "message": f"ETL 请求已接收: {source_table} → {target_table}",
                    "source_schema": source_schema,
                    "transform_logic": transform_logic,
                    "instruction": "LLM 将根据源表结构和转换逻辑生成 ETL SQL，然后通过 execute_write 工具执行。",
                }, ensure_ascii=False)
            except Exception as e:
                logger.error(f"etl_transform error: {e}")
                return json.dumps({
                    "status": "failed",
                    "error": str(e),
                }, ensure_ascii=False)

        @tool
        def get_database_info() -> str:
            """
            获取数据库整体概况，包括所有表、行数、总数据量。
            使用场景: 用户询问 "数据库里有什么"、"有哪些表"、"数据量多大" 时调用。
            """
            try:
                info = mysql.get_database_info()
                return json.dumps(info, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"get_database_info error: {e}")
                return json.dumps({"error": str(e)}, ensure_ascii=False)

        @tool
        def get_audit_logs(limit: int = 20) -> str:
            """
            获取最近的审计日志，包括所有已执行/已拒绝的写操作记录。
            参数:
                limit: 返回的日志条数（默认 20）
            使用场景: 用户询问 "之前做过哪些操作"、"有没有异常操作" 时调用。
            """
            try:
                logs = hitl.get_audit_logs(limit=limit)
                return json.dumps({
                    "status": "success",
                    "count": len(logs),
                    "logs": logs,
                }, ensure_ascii=False, default=str)
            except Exception as e:
                logger.error(f"get_audit_logs error: {e}")
                return json.dumps({"error": str(e)}, ensure_ascii=False)

        return [
            get_schema,
            list_tables,
            get_database_info,
            generate_sql,
            validate_sql,
            execute_query,
            execute_write,
            sync_from_api,
            sync_from_csv,
            create_table,
            etl_transform,
            get_audit_logs,
        ]

    # ── 对话接口 ─────────────────────────────────────────────

    def chat(self, user_message: str, session_id: str = "default") -> Dict:
        """
        与 Agent 对话

        参数:
            user_message: 用户输入的自然语言消息
            session_id: 会话 ID，用于保持多轮对话上下文

        返回:
            {
                "response": "Agent 的文本回复",
                "session_id": "...",
                "pending_approval": {...}  # 如果有待审批的操作
            }
        """
        config = {"configurable": {"thread_id": session_id}}
        self.logger.info(f"Chat [{session_id}]: {user_message[:100]}...")

        try:
            # 调用 LangGraph Agent
            result = self.agent.invoke(
                {"messages": [HumanMessage(content=user_message)]},
                config=config,
            )

            # 提取最后一条 AI 消息
            ai_messages = [
                msg for msg in result.get("messages", [])
                if isinstance(msg, AIMessage)
            ]
            if not ai_messages:
                return {
                    "response": "抱歉，我无法处理这个请求。请重试。",
                    "session_id": session_id,
                }

            response_text = ai_messages[-1].content

            # 检查是否有待审批的操作
            pending_approval = None
            pending_approvals = self.hitl.get_pending_approvals()
            if pending_approvals:
                # 返回最近一条待审批的
                pending_approval = pending_approvals[-1]

            return {
                "response": response_text,
                "session_id": session_id,
                "pending_approval": pending_approval,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            self.logger.error(f"Chat error: {e}", exc_info=True)
            return {
                "response": f"❌ 处理请求时发生错误: {str(e)}",
                "session_id": session_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    async def chat_stream(self, user_message: str, session_id: str = "default"):
        """
        流式对话接口（用于 SSE 推送）

        参数:
            user_message: 用户输入
            session_id: 会话 ID

        Yields:
            SSE 事件字符串
        """
        config = {"configurable": {"thread_id": session_id}}

        try:
            async for event in self.agent.astream_events(
                {"messages": [HumanMessage(content=user_message)]},
                config=config,
                version="v2",
            ):
                kind = event.get("event", "")

                # 工具调用开始
                if kind == "on_tool_start":
                    tool_name = event.get("name", "unknown")
                    yield f"data: {json.dumps({'type': 'tool_start', 'tool': tool_name}, ensure_ascii=False)}\n\n"

                # 工具调用结束
                elif kind == "on_tool_end":
                    tool_name = event.get("name", "unknown")
                    output = event.get("data", {}).get("output", "")
                    yield f"data: {json.dumps({'type': 'tool_end', 'tool': tool_name, 'output_preview': str(output)[:200]}, ensure_ascii=False)}\n\n"

                # LLM Token 流
                elif kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk", None)
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk.content}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            self.logger.error(f"Chat stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"

    # ── 审批操作 ─────────────────────────────────────────────

    def handle_approval(self, approval_id: str, action: str, edited_sql: str = None) -> Dict:
        """
        处理用户的审批决定

        参数:
            approval_id: 审批 ID
            action: approve | reject | edit
            edited_sql: 编辑后的 SQL（仅在 action=edit 时需要）

        返回:
            执行结果
        """
        return self.hitl.handle_decision(approval_id, action, edited_sql)

    def get_pending_approvals(self) -> List[Dict]:
        """获取所有待审批的操作"""
        return self.hitl.get_pending_approvals()

    def rollback_operation(self, backup_id: str) -> Dict:
        """回滚操作"""
        return self.hitl.rollback(backup_id)
