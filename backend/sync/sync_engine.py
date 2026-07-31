"""
外部数据同步引擎 - API/CSV → MySQL
支持从 RESTful API 和 CSV 文件拉取数据，自动建表并同步到 MySQL
"""

import requests
import pandas as pd
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
import hashlib


class ExternalSyncEngine:
    """外部数据同步引擎 - API/CSV → MySQL"""

    def __init__(self, mysql_client):
        self.mysql = mysql_client
        self.logger = logging.getLogger(__name__)

    # ── API 同步 ────────────────────────────────────────────

    def sync_from_api(
        self,
        api_url: str,
        target_table: str,
        sync_mode: str = "append",
        headers: dict = None,
        params: dict = None,
        pagination: dict = None,
        json_path: str = None,
        unique_keys: List[str] = None,
    ) -> Dict:
        """
        从 RESTful API 同步数据到 MySQL

        参数:
            api_url: API 地址
            target_table: 目标表名
            sync_mode: append(追加) | upsert(更新插入) | replace(替换)
            headers: 请求头（如认证 token）
            params: 请求参数
            pagination: 分页配置 {"page_param": "page", "size_param": "page_size", "page_size": 100}
            json_path: JSON 数据的路径（如 "data.items"，用 . 分隔嵌套层级）
            unique_keys: upsert 模式下的唯一键列名
        返回:
            同步结果字典
        """
        all_data = []
        page = 1

        self.logger.info(
            f"Starting API sync: {api_url} → {target_table} (mode={sync_mode})"
        )

        while True:
            # 构建请求参数（处理分页）
            req_params = dict(params or {})
            if pagination:
                req_params[pagination.get("page_param", "page")] = page
                req_params[pagination.get("size_param", "page_size")] = (
                    pagination.get("page_size", 100)
                )

            # 发送请求
            try:
                response = requests.get(
                    api_url,
                    headers=headers or {},
                    params=req_params or None,
                    timeout=60,
                )
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.RequestException as e:
                self.logger.error(f"API request failed: {e}")
                return {
                    "status": "failed",
                    "error": f"API 请求失败: {str(e)}",
                }

            # 从嵌套 JSON 中提取数据
            records = self._extract_records(data, json_path)
            if not records:
                break

            all_data.extend(records)

            # 判断是否还有下一页
            if not pagination or not self._has_next_page(data, pagination, len(records)):
                break
            page += 1

        return self._write_to_mysql(
            all_data, target_table, sync_mode, unique_keys,
            source=f"api:{api_url}",
        )

    # ── CSV 同步 ─────────────────────────────────────────────

    def sync_from_csv(
        self,
        file_path: str,
        target_table: str,
        sync_mode: str = "append",
        encoding: str = "utf-8",
        delimiter: str = ",",
        unique_keys: List[str] = None,
    ) -> Dict:
        """
        从 CSV 文件导入数据到 MySQL

        参数:
            file_path: CSV 文件路径
            target_table: 目标表名
            sync_mode: append(追加) | upsert(更新插入) | replace(替换)
            encoding: 文件编码
            delimiter: 列分隔符
            unique_keys: upsert 模式下的唯一键列名
        """
        self.logger.info(
            f"Starting CSV sync: {file_path} → {target_table} (mode={sync_mode})"
        )

        try:
            df = pd.read_csv(file_path, encoding=encoding, delimiter=delimiter)
            df = df.where(pd.notnull(df), None)  # NaN → None
            records = df.to_dict(orient="records")
            self.logger.info(f"Read {len(records)} rows from CSV")
        except Exception as e:
            self.logger.error(f"CSV read failed: {e}")
            return {
                "status": "failed",
                "error": f"CSV 文件读取失败: {str(e)}",
            }

        return self._write_to_mysql(
            records, target_table, sync_mode, unique_keys,
            source=f"csv:{file_path}",
        )

    # ── JSON 文件同步 ────────────────────────────────────────

    def sync_from_json(
        self,
        file_path: str,
        target_table: str,
        sync_mode: str = "append",
        encoding: str = "utf-8",
        json_path: str = None,
        unique_keys: List[str] = None,
    ) -> Dict:
        """从 JSON 文件导入数据到 MySQL"""
        self.logger.info(f"Starting JSON sync: {file_path} → {target_table}")

        try:
            with open(file_path, "r", encoding=encoding) as f:
                data = json.load(f)
            records = self._extract_records(data, json_path)
        except Exception as e:
            self.logger.error(f"JSON read failed: {e}")
            return {"status": "failed", "error": f"JSON 文件读取失败: {str(e)}"}

        return self._write_to_mysql(
            records, target_table, sync_mode, unique_keys,
            source=f"json:{file_path}",
        )

    # ── 核心写入逻辑 ─────────────────────────────────────────

    def _write_to_mysql(
        self,
        data: List[Dict],
        table: str,
        sync_mode: str,
        unique_keys: List[str] = None,
        source: str = None,
    ) -> Dict:
        """将数据写入 MySQL（核心写入逻辑）"""
        if not data:
            return {
                "status": "success",
                "table": table,
                "total": 0,
                "inserted": 0,
                "sync_mode": sync_mode,
                "message": "无数据需要同步",
                "timestamp": datetime.now().isoformat(),
            }

        # 1. 自动建表（如果表不存在）
        if not self.mysql.table_exists(table):
            self._auto_create_table(table, data[0])

        # 2. 添加同步元数据列（如果不存在）
        self._ensure_sync_columns(table)

        # 3. 为每条记录添加同步批次标记
        batch_id = hashlib.md5(
            f"{table}_{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]
        for record in data:
            record["sync_batch_id"] = batch_id
            if "sync_time" not in record:
                record["sync_time"] = datetime.now().isoformat()

        # 4. 按模式写入
        inserted = 0
        try:
            if sync_mode == "append":
                inserted = self.mysql.bulk_insert(table, data)
            elif sync_mode == "upsert":
                inserted = self.mysql.upsert_data(
                    table, data, unique_keys or ["id"]
                )
            elif sync_mode == "replace":
                self.mysql.truncate_table(table)
                inserted = self.mysql.bulk_insert(table, data)
            else:
                return {"status": "failed", "error": f"不支持的同步模式: {sync_mode}"}
        except Exception as e:
            self.logger.error(f"Write to MySQL failed: {e}")
            self._log_sync(table, len(data), 0, sync_mode, "failed", source)
            return {
                "status": "failed",
                "table": table,
                "total": len(data),
                "inserted": 0,
                "error": str(e),
            }

        # 5. 记录同步日志
        self._log_sync(table, len(data), inserted, sync_mode, "success", source)

        # 6. 记录数据血缘
        if source:
            self._log_lineage(source, table, f"sync_{sync_mode}")

        return {
            "status": "success",
            "table": table,
            "total": len(data),
            "inserted": inserted,
            "sync_mode": sync_mode,
            "batch_id": batch_id,
            "timestamp": datetime.now().isoformat(),
        }

    # ── 辅助方法 ─────────────────────────────────────────────

    def _extract_records(self, data: Any, json_path: str = None) -> List[Dict]:
        """从嵌套 JSON 中提取数据记录"""
        if json_path:
            parts = json_path.split(".")
            for part in parts:
                if isinstance(data, dict):
                    data = data.get(part)
                elif isinstance(data, list):
                    # 如果是列表且路径指向元素内字段，取第一个元素
                    data = data[0].get(part) if data else None
                if data is None:
                    return []

        if isinstance(data, list):
            # 确保列表中的每个元素都是字典
            return [
                item if isinstance(item, dict) else {"value": item}
                for item in data
            ]
        elif isinstance(data, dict):
            # 尝试在字典值中找列表
            for value in data.values():
                if isinstance(value, list):
                    return [
                        item if isinstance(item, dict) else {"value": item}
                        for item in value
                    ]
            return [data]

        return []

    def _has_next_page(
        self, response_data: Any, pagination: dict, last_count: int
    ) -> bool:
        """判断 API 是否还有下一页"""
        page_size = pagination.get("page_size", 100)
        # 如果返回的数据量小于 page_size，说明到最后一页了
        return last_count >= page_size

    def _auto_create_table(self, table_name: str, sample_record: dict):
        """根据数据样本自动推断并创建表"""
        columns = []
        for key, value in sample_record.items():
            if not key.startswith("_"):  # 跳过内部字段
                col_type = self._infer_type(value)
                columns.append(f"`{key}` {col_type}")

        # 添加同步元数据列
        columns.append("`sync_batch_id` VARCHAR(64)")
        columns.append("`sync_time` DATETIME")

        create_def = ", ".join(columns)
        self.mysql.create_table_from_schema(table_name, create_def)
        self.logger.info(f"Auto-created table `{table_name}` with {len(columns)} columns")

    def _ensure_sync_columns(self, table_name: str):
        """确保表有同步元数据列"""
        schema = self.mysql.get_table_schema(table_name)
        if "error" in schema:
            return
        existing_cols = {c["name"] for c in schema.get("columns", [])}

        alter_parts = []
        if "sync_batch_id" not in existing_cols:
            alter_parts.append("ADD COLUMN `sync_batch_id` VARCHAR(64)")
        if "sync_time" not in existing_cols:
            alter_parts.append("ADD COLUMN `sync_time` DATETIME")

        for part in alter_parts:
            try:
                self.mysql.execute_update(
                    f"ALTER TABLE `{table_name}` {part}"
                )
            except Exception:
                pass  # 列可能已存在

    def _infer_type(self, value) -> str:
        """根据值类型推断 MySQL 字段类型"""
        if value is None:
            return "TEXT"
        if isinstance(value, bool):
            return "TINYINT(1)"
        if isinstance(value, int):
            if value > 2147483647 or value < -2147483648:
                return "BIGINT"
            return "INT"
        if isinstance(value, float):
            return "DOUBLE"
        if isinstance(value, (dict, list)):
            return "JSON"
        s = str(value)
        if len(s) > 65535:
            return "LONGTEXT"
        if len(s) > 255:
            return "TEXT"
        return "VARCHAR(512)"

    def _log_sync(
        self,
        table: str,
        total: int,
        inserted: int,
        mode: str,
        status: str,
        source: str = None,
    ):
        """记录同步日志到审计表"""
        try:
            log_sql = """
                INSERT INTO sync_log
                (table_name, total_rows, inserted_rows, sync_mode, source, status, created_at)
                VALUES (:table, :total, :inserted, :mode, :source, :status, NOW())
            """
            self.mysql.execute_update(
                log_sql,
                {
                    "table": table,
                    "total": total,
                    "inserted": inserted,
                    "mode": mode,
                    "source": source or "",
                    "status": status,
                },
            )
        except Exception as e:
            self.logger.warning(f"Failed to write sync log: {e}")

    def _log_lineage(self, source: str, target_table: str, operation: str):
        """记录数据血缘"""
        try:
            lineage_sql = """
                INSERT INTO data_lineage
                (source_type, source_name, target_table, operation, created_at)
                VALUES (:source_type, :source_name, :target_table, :operation, NOW())
            """
            source_type = source.split(":", 1)[0] if ":" in source else "unknown"
            self.mysql.execute_update(
                lineage_sql,
                {
                    "source_type": source_type,
                    "source_name": source,
                    "target_table": target_table,
                    "operation": operation,
                },
            )
        except Exception as e:
            self.logger.warning(f"Failed to write lineage: {e}")

    # ── 同步日志查询 ─────────────────────────────────────────

    def get_sync_logs(self, limit: int = 50) -> List[Dict]:
        """获取最近的同步日志"""
        sql = "SELECT * FROM sync_log ORDER BY created_at DESC LIMIT :limit"
        return self.mysql.execute_query(sql, {"limit": limit})
