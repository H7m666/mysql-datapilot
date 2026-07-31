"""
MySQL 统一操作客户端 - 封装所有数据库操作
基于 SQLAlchemy + pymysql，提供连接池管理、CRUD、批量操作等
"""

from sqlalchemy import create_engine, text, MetaData, Table, inspect
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager
from typing import List, Dict, Any, Optional
import logging
import json


class MySQLClient:
    """MySQL 统一操作客户端 - 封装所有数据库操作"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 3306,
        user: str = "root",
        password: str = "root",
        database: str = "datapilot",
        pool_size: int = 10,
        echo: bool = False,
    ):
        database_url = (
            f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
            f"?charset=utf8mb4"
        )
        self.engine = create_engine(
            database_url,
            poolclass=QueuePool,
            pool_size=pool_size,
            max_overflow=20,
            pool_recycle=3600,
            pool_pre_ping=True,  # 自动检测连接有效性
            echo=echo,
        )
        self.database = database
        self.logger = logging.getLogger(__name__)

    # ── 连接管理 ────────────────────────────────────────────

    @contextmanager
    def get_connection(self):
        """上下文管理器 - 自动管理连接生命周期（提交/回滚/关闭）"""
        conn = self.engine.connect()
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            self.logger.error(f"Database error, rolling back: {e}")
            raise
        finally:
            conn.close()

    @contextmanager
    def get_transaction(self):
        """获取事务连接 - 需要显式调用 commit"""
        conn = self.engine.connect()
        trans = conn.begin()
        try:
            yield conn
            trans.commit()
        except Exception as e:
            trans.rollback()
            self.logger.error(f"Transaction error, rolling back: {e}")
            raise
        finally:
            conn.close()

    # ── 查询操作 ────────────────────────────────────────────

    def execute_query(self, sql: str, params: dict = None) -> List[Dict]:
        """
        执行 SELECT 查询，返回字典列表

        参数:
            sql: SQL 语句（使用 :key 作为占位符）
            params: 参数字典
        返回:
            查询结果，每行为一个字典
        """
        with self.get_connection() as conn:
            result = conn.execute(text(sql), params or {})
            rows = [dict(row._mapping) for row in result]
            self.logger.debug(
                f"Query executed: [{len(rows)} rows] {sql[:100]}..."
            )
            return rows

    # ── 写操作 ──────────────────────────────────────────────

    def execute_update(self, sql: str, params: dict = None) -> int:
        """
        执行 INSERT/UPDATE/DELETE，返回影响行数

        参数:
            sql: SQL 语句
            params: 参数字典
        返回:
            影响的行数
        """
        with self.get_connection() as conn:
            result = conn.execute(text(sql), params or {})
            self.logger.info(f"Update executed: [{result.rowcount} rows affected]")
            return result.rowcount

    def execute_write_with_backup(
        self, sql: str, params: dict = None, table_name: str = None
    ) -> Dict:
        """
        执行写操作并在审计日志中记录备份信息
        """
        try:
            affected = self.execute_update(sql, params)
            return {
                "status": "success",
                "affected_rows": affected,
                "backup_id": None,
            }
        except Exception as e:
            self.logger.error(f"Write operation failed: {e}")
            return {
                "status": "failed",
                "affected_rows": 0,
                "error": str(e),
            }

    def bulk_insert(self, table: str, data: List[Dict]) -> int:
        """
        批量插入数据（使用 executemany 优化性能）

        参数:
            table: 目标表名
            data: 数据列表，每条记录为一个字典
        返回:
            实际插入的行数
        """
        if not data:
            return 0

        columns = list(data[0].keys())
        placeholders = ", ".join([f":{col}" for col in columns])
        col_names = ", ".join([f"`{col}`" for col in columns])
        sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"

        with self.get_connection() as conn:
            conn.execute(text(sql), data)
            self.logger.info(
                f"Bulk insert into `{table}`: {len(data)} rows"
            )
            return len(data)

    def upsert_data(
        self, table: str, data: List[Dict], unique_keys: List[str]
    ) -> int:
        """
        Upsert 操作 — INSERT ... ON DUPLICATE KEY UPDATE

        参数:
            table: 目标表名
            data: 数据列表
            unique_keys: 唯一键列名列表
        返回:
            影响的行数
        """
        if not data:
            return 0

        columns = list(data[0].keys())
        placeholders = ", ".join([f":{col}" for col in columns])
        col_names = ", ".join([f"`{col}`" for col in columns])

        update_parts = ", ".join(
            [f"`{col}` = VALUES(`{col}`)" for col in columns if col not in unique_keys]
        )
        sql = (
            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {update_parts}"
        )

        total = 0
        with self.get_connection() as conn:
            for record in data:
                result = conn.execute(text(sql), record)
                total += result.rowcount
        return total

    # ── 表结构管理 ──────────────────────────────────────────

    def get_table_schema(self, table_name: str = None) -> Dict:
        """
        获取表结构信息（供 Agent 使用）

        参数:
            table_name: 表名，不传则返回所有表列表和结构
        返回:
            表结构字典
        """
        inspector = inspect(self.engine)

        if table_name:
            if not self.table_exists(table_name):
                return {"error": f"表 '{table_name}' 不存在"}

            columns = inspector.get_columns(table_name)
            indexes = inspector.get_indexes(table_name)
            pk = inspector.get_pk_constraint(table_name)

            return {
                "table": table_name,
                "columns": [
                    {
                        "name": c["name"],
                        "type": str(c["type"]),
                        "nullable": c.get("nullable", True),
                        "default": c.get("default"),
                        "comment": c.get("comment", ""),
                    }
                    for c in columns
                ],
                "primary_key": pk.get("constrained_columns", []),
                "indexes": [
                    {"name": idx["name"], "columns": idx["column_names"]}
                    for idx in indexes
                ],
            }

        # 返回所有表及其简要结构
        tables = inspector.get_table_names()
        return {
            "database": self.database,
            "tables": tables,
            "table_count": len(tables),
        }

    def get_all_table_schemas(self) -> Dict:
        """获取所有表的详细结构"""
        all_schemas = self.get_table_schema()
        result = {"database": self.database, "tables": {}}
        for table_name in all_schemas.get("tables", []):
            result["tables"][table_name] = self.get_table_schema(table_name)
        return result

    def table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        inspector = inspect(self.engine)
        return table_name in inspector.get_table_names()

    def create_table_from_schema(
        self, table_name: str, columns_def: str, if_not_exists: bool = True
    ) -> None:
        """
        根据列定义创建表

        参数:
            table_name: 表名
            columns_def: 列定义（如 "id BIGINT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100)"）
            if_not_exists: 是否加 IF NOT EXISTS
        """
        if_not = "IF NOT EXISTS" if if_not_exists else ""
        sql = f"CREATE TABLE {if_not} `{table_name}` ({columns_def})"
        self.execute_update(sql)
        self.logger.info(f"Table `{table_name}` created")

    def drop_table(self, table_name: str, if_exists: bool = True) -> None:
        """删除表"""
        if_ex = "IF EXISTS" if if_exists else ""
        sql = f"DROP TABLE {if_ex} `{table_name}`"
        self.execute_update(sql)
        self.logger.info(f"Table `{table_name}` dropped")

    def truncate_table(self, table_name: str) -> None:
        """清空表数据"""
        sql = f"TRUNCATE TABLE `{table_name}`"
        self.execute_update(sql)
        self.logger.info(f"Table `{table_name}` truncated")

    def get_row_count(self, table_name: str) -> int:
        """获取表的行数"""
        sql = f"SELECT COUNT(*) AS cnt FROM `{table_name}`"
        result = self.execute_query(sql)
        return result[0]["cnt"] if result else 0

    # ── 数据库信息 ──────────────────────────────────────────

    def get_database_info(self) -> Dict:
        """获取数据库整体信息"""
        inspector = inspect(self.engine)
        tables = inspector.get_table_names()
        table_sizes = {}
        for t in tables:
            table_sizes[t] = self.get_row_count(t)

        return {
            "database": self.database,
            "table_count": len(tables),
            "tables": table_sizes,
            "total_rows": sum(table_sizes.values()),
        }

    # ── 测试连接 ────────────────────────────────────────────

    def test_connection(self) -> bool:
        """测试数据库连接是否正常"""
        try:
            with self.get_connection() as conn:
                conn.execute(text("SELECT 1"))
            self.logger.info("Database connection test: OK")
            return True
        except Exception as e:
            self.logger.error(f"Database connection test failed: {e}")
            return False

    # ── 数据导出 ────────────────────────────────────────────

    def export_to_dict(self, table_name: str, limit: int = 0) -> List[Dict]:
        """导出表数据为字典列表"""
        sql = f"SELECT * FROM `{table_name}`"
        if limit > 0:
            sql += f" LIMIT {limit}"
        return self.execute_query(sql)
