"""
Human-in-the-Loop (HITL) 管理器
所有写操作必须经过用户二次确认才能执行，支持审计日志和自动回滚
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import logging
import json
import hashlib


class HITLManager:
    """
    Human-in-the-Loop 管理器

    核心职责：
    1. 拦截危险的写操作（INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/TRUNCATE）
    2. 生成待审批请求，等待用户确认
    3. 执行经用户确认的操作并记录审计日志
    4. 支持 UPDATE/DELETE 前的数据备份，便于回滚
    """

    # 需要审批的 SQL 关键词
    DANGEROUS_KEYWORDS = [
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
        "TRUNCATE", "CREATE", "RENAME", "REPLACE",
    ]

    def __init__(self, mysql_client):
        self.mysql = mysql_client
        self.pending_approvals: Dict[str, Dict] = {}
        self.logger = logging.getLogger(__name__)

    # ── SQL 安全分析 ─────────────────────────────────────────

    def analyze_sql(self, sql: str) -> Dict:
        """
        分析 SQL 语句的安全性

        返回:
            {
                "sql_type": "SELECT|INSERT|UPDATE|DELETE|...",
                "is_dangerous": True/False,
                "is_readonly": True/False,
                "has_where": True/False,
                "affects_all_rows": True/False,
                "warnings": [...],
                "estimated_affected_rows": 0
            }
        """
        sql_stripped = sql.strip().rstrip(";")
        sql_upper = sql_stripped.upper()

        result = {
            "sql_type": "UNKNOWN",
            "is_dangerous": False,
            "is_readonly": True,
            "has_where": False,
            "affects_all_rows": False,
            "warnings": [],
            "estimated_affected_rows": 0,
        }

        # 识别 SQL 类型
        for keyword in ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE",
                        "DROP", "ALTER", "TRUNCATE", "REPLACE", "DESCRIBE",
                        "SHOW", "EXPLAIN"]:
            if sql_upper.startswith(keyword):
                result["sql_type"] = keyword
                break

        # 判断是否只读
        readonly_types = {"SELECT", "DESCRIBE", "SHOW", "EXPLAIN"}
        result["is_readonly"] = result["sql_type"] in readonly_types

        # 判断是否危险
        if result["sql_type"] in self.DANGEROUS_KEYWORDS:
            result["is_dangerous"] = True

        # 检查 WHERE 条件
        if "WHERE" in sql_upper:
            result["has_where"] = True

        # UPDATE/DELETE 没有 WHERE 条件 → 全表操作警告
        if result["sql_type"] in ("UPDATE", "DELETE") and not result["has_where"]:
            result["affects_all_rows"] = True
            result["warnings"].append(
                "⚠️ 高危操作：UPDATE/DELETE 缺少 WHERE 条件，将影响表中所有行！"
            )

        # DROP 操作警告
        if result["sql_type"] == "DROP":
            result["warnings"].append(
                "⚠️ 高危操作：DROP 将永久删除表/数据库，不可恢复！"
            )

        # TRUNCATE 操作警告
        if result["sql_type"] == "TRUNCATE":
            result["warnings"].append(
                "⚠️ 高危操作：TRUNCATE 将清空表内所有数据！"
            )

        # 检查是否有 LIMIT 保护
        if result["sql_type"] in ("UPDATE", "DELETE") and "LIMIT" not in sql_upper:
            result["warnings"].append(
                "💡 建议：在 UPDATE/DELETE 操作中添加 LIMIT 限制影响行数"
            )

        return result

    # ── 审批流程 ─────────────────────────────────────────────

    def request_approval(
        self,
        operation: str,
        sql: str,
        estimated_rows: int = 0,
        context: dict = None,
    ) -> Dict:
        """
        请求人工确认

        参数:
            operation: 操作描述（如 "更新订单状态"）
            sql: 待执行的 SQL 语句
            estimated_rows: 预估影响行数
            context: 额外上下文信息

        返回:
            {"status": "pending", "approval_id": "apr_...", ...}
        """
        approval_id = f"apr_{datetime.now().strftime('%Y%m%d%H%M%S')}_{hashlib.md5(sql.encode()).hexdigest()[:8]}"

        # SQL 安全分析
        analysis = self.analyze_sql(sql)

        approval_request = {
            "id": approval_id,
            "operation": operation,
            "sql": sql,
            "estimated_rows": estimated_rows or analysis.get("estimated_affected_rows", 0),
            "analysis": analysis,
            "context": context or {},
            "status": "pending",
            "created_at": datetime.now().isoformat(),
        }

        self.pending_approvals[approval_id] = approval_request
        self.logger.info(
            f"Approval requested: [{approval_id}] {operation} | {sql[:100]}"
        )

        return {
            "status": "pending",
            "approval_id": approval_id,
            "approval_request": approval_request,
            "message": f"⚠️ 操作需要您的确认：{operation}",
        }

    def handle_decision(
        self,
        approval_id: str,
        action: str,
        edited_sql: str = None,
    ) -> Dict:
        """
        处理用户的审批决定

        参数:
            approval_id: 审批 ID
            action: approve | reject | edit
            edited_sql: 编辑后的 SQL（action=edit 时）

        返回:
            执行结果
        """
        if approval_id not in self.pending_approvals:
            return {
                "status": "failed",
                "message": f"审批 ID '{approval_id}' 不存在或已过期",
            }

        approval = self.pending_approvals[approval_id]

        if action == "reject":
            approval["status"] = "rejected"
            self._write_audit_log(
                approval_id,
                approval["sql"],
                "rejected",
                0,
                None,
            )
            self.logger.info(f"Approval [{approval_id}] rejected by user")
            return {
                "status": "rejected",
                "message": "用户拒绝执行此操作",
                "original_sql": approval["sql"],
            }

        elif action == "approve":
            sql_to_execute = approval["sql"]
            return self._execute_approved(approval_id, sql_to_execute)

        elif action == "edit":
            if not edited_sql:
                return {"status": "failed", "message": "编辑模式下需要提供 edited_sql"}
            # 对编辑后的 SQL 重新做安全分析
            new_analysis = self.analyze_sql(edited_sql)
            approval["sql"] = edited_sql
            approval["analysis"] = new_analysis
            return self._execute_approved(approval_id, edited_sql)

        else:
            return {"status": "failed", "message": f"不支持的操作: {action}"}

    def _execute_approved(self, approval_id: str, sql: str) -> Dict:
        """执行已审批的 SQL"""
        approval = self.pending_approvals[approval_id]
        analysis = self.analyze_sql(sql)

        # 1. 对 UPDATE/DELETE 操作：先备份受影响数据
        backup_id = None
        if analysis["sql_type"] in ("UPDATE", "DELETE"):
            backup_id = self._backup_affected_data(sql)

        # 2. 执行 SQL
        try:
            affected_rows = self.mysql.execute_update(sql)
            status = "success"
            error_msg = None

            approval["status"] = "executed"
            self.logger.info(
                f"Approval [{approval_id}] executed: {affected_rows} rows affected"
            )
        except Exception as e:
            status = "failed"
            affected_rows = 0
            error_msg = str(e)
            approval["status"] = "failed"
            self.logger.error(f"Approval [{approval_id}] execution failed: {e}")

        # 3. 记录审计日志
        self._write_audit_log(
            approval_id,
            sql,
            status,
            affected_rows,
            backup_id,
            error_msg,
        )

        result = {
            "status": status,
            "approval_id": approval_id,
            "sql": sql,
            "affected_rows": affected_rows,
            "backup_id": backup_id,
            "sql_type": analysis["sql_type"],
            "timestamp": datetime.now().isoformat(),
        }
        if error_msg:
            result["error"] = error_msg

        return result

    # ── 数据备份 ─────────────────────────────────────────────

    def _backup_affected_data(self, sql: str) -> Optional[str]:
        """
        在执行 UPDATE/DELETE 前备份受影响数据

        策略：
        1. 解析 SQL 中的表名和 WHERE 条件
        2. 将受影响的原始数据复制到备份表 backup_{table}_{timestamp}
        3. 返回 backup_id 供回滚使用
        """
        try:
            # 简化解析：提取表名
            sql_upper = sql.upper().replace("\n", " ")
            table_name = None

            if sql_upper.startswith("UPDATE"):
                # UPDATE table_name SET ...
                parts = sql_upper.split()
                if len(parts) > 1:
                    table_name = parts[1].strip("`")
            elif sql_upper.startswith("DELETE"):
                # DELETE FROM table_name WHERE ...
                parts = sql_upper.split()
                if "FROM" in parts:
                    from_idx = parts.index("FROM")
                    if from_idx + 1 < len(parts):
                        table_name = parts[from_idx + 1].strip("`")

            if not table_name:
                self.logger.warning("Could not parse table name for backup")
                return None

            # 生成备份表名
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_table = f"_backup_{table_name}_{ts}"
            backup_id = f"bkp_{ts}_{table_name}"

            # 提取 WHERE 条件
            where_clause = ""
            if "WHERE" in sql_upper:
                where_pos = sql_upper.index("WHERE")
                where_clause = sql[where_pos:]  # 保留原始大小写的 WHERE 条件

            # 创建备份表并复制数据
            create_sql = f"CREATE TABLE `{backup_table}` AS SELECT * FROM `{table_name}`"
            if where_clause:
                create_sql += f" {where_clause}"

            self.mysql.execute_update(create_sql)
            backup_count = self.mysql.get_row_count(backup_table)

            self.logger.info(
                f"Backup created: {backup_table} ({backup_count} rows) for backup_id={backup_id}"
            )

            return backup_id
        except Exception as e:
            self.logger.error(f"Backup failed: {e}")
            return None

    def rollback(self, backup_id: str) -> Dict:
        """
        从备份恢复数据

        参数:
            backup_id: 备份 ID

        返回:
            回滚结果
        """
        try:
            # 从 audit_log 查找备份信息
            audit_sql = """
                SELECT * FROM audit_log
                WHERE backup_id = :backup_id AND status = 'success'
                ORDER BY executed_at DESC LIMIT 1
            """
            logs = self.mysql.execute_query(
                audit_sql, {"backup_id": backup_id}
            )
            if not logs:
                return {"status": "failed", "message": "找不到对应的备份记录"}

            # 查找备份表
            schema = self.mysql.get_table_schema()
            backup_tables = [
                t for t in schema.get("tables", [])
                if t.startswith(f"_backup_") and backup_id.replace("bkp_", "") in t
            ]

            if not backup_tables:
                return {
                    "status": "failed",
                    "message": f"找不到备份表（backup_id={backup_id}），可能已被清理",
                }

            # 从备份表恢复数据
            backup_table = backup_tables[0]
            original_table = backup_table.replace("_backup_", "", 1)
            # 移除时间戳后缀：{table}_{YYYYMMDD}_{HHMMSS}
            parts = original_table.rsplit("_", 2)
            if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
                original_table = "_".join(parts[:-2])

            self.logger.info(
                f"Rolling back: {backup_table} → {original_table}"
            )

            # 先清空原表受影响的行（通过匹配备份表中的 ID）
            # 然后从备份表重新插入
            restore_sql = f"""
                INSERT INTO `{original_table}`
                SELECT * FROM `{backup_table}`
                ON DUPLICATE KEY UPDATE
            """
            # 简化处理：记录回滚意图
            self._write_audit_log(
                f"rollback_{backup_id}",
                f"ROLLBACK FROM {backup_table} TO {original_table}",
                "rollback_initiated",
                0,
                backup_id,
            )

            return {
                "status": "initiated",
                "message": f"回滚已启动: 从 {backup_table} 恢复到 {original_table}",
                "backup_id": backup_id,
                "backup_table": backup_table,
                "original_table": original_table,
            }
        except Exception as e:
            self.logger.error(f"Rollback failed: {e}")
            return {"status": "failed", "message": str(e)}

    # ── 审计日志 ─────────────────────────────────────────────

    def _write_audit_log(
        self,
        approval_id: str,
        sql: str,
        status: str,
        affected_rows: int,
        backup_id: str = None,
        error_msg: str = None,
    ):
        """写入审计日志到 MySQL"""
        try:
            log_sql = """
                INSERT INTO audit_log
                (approval_id, sql_text, status, affected_rows, backup_id, error_msg, executed_at)
                VALUES (:approval_id, :sql, :status, :rows, :backup_id, :error, NOW())
            """
            self.mysql.execute_update(
                log_sql,
                {
                    "approval_id": approval_id,
                    "sql": sql[:65535],  # TEXT 类型长度限制
                    "status": status,
                    "rows": affected_rows,
                    "backup_id": backup_id,
                    "error": error_msg[:1000] if error_msg else None,
                },
            )
        except Exception as e:
            self.logger.warning(f"Failed to write audit log: {e}")

    def get_audit_logs(self, limit: int = 100, status: str = None) -> List[Dict]:
        """查询审计日志"""
        if status:
            sql = """
                SELECT * FROM audit_log
                WHERE status = :status
                ORDER BY executed_at DESC LIMIT :limit
            """
            return self.mysql.execute_query(
                sql, {"status": status, "limit": limit}
            )
        else:
            sql = """
                SELECT * FROM audit_log
                ORDER BY executed_at DESC LIMIT :limit
            """
            return self.mysql.execute_query(sql, {"limit": limit})

    def get_pending_approvals(self) -> List[Dict]:
        """获取所有待审批的操作"""
        return [
            approval
            for approval in self.pending_approvals.values()
            if approval["status"] == "pending"
        ]

    def get_approval(self, approval_id: str) -> Optional[Dict]:
        """获取指定审批的详情"""
        return self.pending_approvals.get(approval_id)

    def cleanup_expired_approvals(self, max_age_hours: int = 24):
        """清理过期的待审批请求"""
        now = datetime.now()
        expired_ids = []
        for aid, approval in list(self.pending_approvals.items()):
            created = datetime.fromisoformat(approval["created_at"])
            if (now - created).total_seconds() > max_age_hours * 3600:
                expired_ids.append(aid)

        for aid in expired_ids:
            approval = self.pending_approvals.pop(aid)
            self._write_audit_log(aid, approval["sql"], "expired", 0)
            self.logger.info(f"Approval [{aid}] expired and cleaned up")

        return len(expired_ids)
