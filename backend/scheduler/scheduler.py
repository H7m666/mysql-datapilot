"""
定时任务调度引擎 - 基于 APScheduler
管理定时同步/ETL 任务，任务定义持久化到 MySQL
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable
import logging
import uuid


class TaskScheduler:
    """
    定时任务调度器

    功能：
    - 创建/删除/暂停/恢复定时任务
    - 支持 Cron 表达式
    - 任务定义持久化到 MySQL
    - 执行日志记录
    """

    def __init__(self, mysql_client, sync_engine=None):
        self.mysql = mysql_client
        self.sync_engine = sync_engine
        self.logger = logging.getLogger(__name__)

        # 配置 APScheduler
        jobstores = {"default": MemoryJobStore()}
        executors = {
            "default": ThreadPoolExecutor(max_workers=5)
        }
        job_defaults = {
            "coalesce": True,          # 合并错过的任务
            "max_instances": 1,         # 同一任务最多同时运行 1 个实例
            "misfire_grace_time": 300,  # 错过 5 分钟内的任务仍然执行
        }

        self.scheduler = BackgroundScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
        )

        # 任务执行器注册表
        self._executors: Dict[str, Callable] = {}

        self._register_default_executors()

    # ── 生命周期 ─────────────────────────────────────────────

    def start(self):
        """启动调度器"""
        if not self.scheduler.running:
            self.scheduler.start()
            self.logger.info("Scheduler started")
            # 从数据库恢复任务
            self._restore_tasks()

    def shutdown(self, wait: bool = True):
        """关闭调度器"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)
            self.logger.info("Scheduler shutdown")

    # ── 任务执行器注册 ───────────────────────────────────────

    def _register_default_executors(self):
        """注册默认的任务执行器"""
        if self.sync_engine:
            self.register_executor("sync_api", self._execute_sync_api)
            self.register_executor("sync_csv", self._execute_sync_csv)

    def register_executor(self, task_type: str, executor_fn: Callable):
        """注册自定义任务执行器"""
        self._executors[task_type] = executor_fn
        self.logger.info(f"Executor registered for type: {task_type}")

    # ── 任务 CRUD ────────────────────────────────────────────

    def create_task(
        self,
        name: str,
        cron_expr: str,
        task_type: str,
        params: Dict[str, Any],
        enabled: bool = True,
    ) -> str:
        """
        创建定时任务

        参数:
            name: 任务名称
            cron_expr: Cron 表达式（如 "0 2 * * *" 表示每天凌晨2点）
            task_type: 任务类型（sync_api | sync_csv | etl | custom）
            params: 任务参数字典
            enabled: 是否启用

        返回:
            task_id
        """
        task_id = f"task_{uuid.uuid4().hex[:12]}"

        # 1. 持久化到 MySQL
        try:
            save_sql = """
                INSERT INTO scheduled_tasks
                (task_id, name, cron_expr, task_type, params, enabled, created_at)
                VALUES (:task_id, :name, :cron, :type, :params, :enabled, NOW())
            """
            self.mysql.execute_update(
                save_sql,
                {
                    "task_id": task_id,
                    "name": name,
                    "cron": cron_expr,
                    "type": task_type,
                    "params": str(params),  # JSON 序列化
                    "enabled": 1 if enabled else 0,
                },
            )
        except Exception as e:
            self.logger.error(f"Failed to save task to MySQL: {e}")
            raise

        # 2. 注册到 APScheduler（仅在启用时）
        if enabled:
            self._add_job(task_id, name, cron_expr, task_type, params)

        self.logger.info(f"Task created: [{task_id}] {name} (cron={cron_expr})")
        return task_id

    def _add_job(self, task_id: str, name: str, cron_expr: str,
                 task_type: str, params: Dict):
        """向 APScheduler 添加任务"""
        if task_type not in self._executors:
            self.logger.warning(
                f"No executor registered for type '{task_type}', "
                f"available: {list(self._executors.keys())}"
            )
            return

        self.scheduler.add_job(
            func=self._execute_task,
            trigger=CronTrigger.from_crontab(cron_expr),
            id=task_id,
            name=name,
            args=[task_id],
            replace_existing=True,
        )

    def delete_task(self, task_id: str) -> bool:
        """删除定时任务"""
        try:
            # 从 APScheduler 移除
            try:
                self.scheduler.remove_job(task_id)
            except Exception:
                pass  # 可能已经不存在

            # 从 MySQL 删除
            self.mysql.execute_update(
                "DELETE FROM scheduled_tasks WHERE task_id = :task_id",
                {"task_id": task_id},
            )

            self.logger.info(f"Task deleted: [{task_id}]")
            return True
        except Exception as e:
            self.logger.error(f"Failed to delete task: {e}")
            return False

    def pause_task(self, task_id: str) -> bool:
        """暂停任务"""
        try:
            self.scheduler.pause_job(task_id)
            self.mysql.execute_update(
                "UPDATE scheduled_tasks SET enabled = 0 WHERE task_id = :task_id",
                {"task_id": task_id},
            )
            self.logger.info(f"Task paused: [{task_id}]")
            return True
        except Exception as e:
            self.logger.error(f"Failed to pause task: {e}")
            return False

    def resume_task(self, task_id: str) -> bool:
        """恢复任务"""
        try:
            task = self._get_task_from_db(task_id)
            if not task:
                return False

            self.scheduler.resume_job(task_id)
            self.mysql.execute_update(
                "UPDATE scheduled_tasks SET enabled = 1 WHERE task_id = :task_id",
                {"task_id": task_id},
            )
            self.logger.info(f"Task resumed: [{task_id}]")
            return True
        except Exception as e:
            self.logger.error(f"Failed to resume task: {e}")
            return False

    def run_task_now(self, task_id: str) -> bool:
        """立即手动执行一次任务"""
        try:
            job = self.scheduler.get_job(task_id)
            if job:
                job.modify(next_run_time=datetime.now())
                self.logger.info(f"Task triggered manually: [{task_id}]")
                return True
            else:
                # 从数据库加载并执行一次
                task = self._get_task_from_db(task_id)
                if task:
                    self._execute_task(task_id)
                    return True
                return False
        except Exception as e:
            self.logger.error(f"Failed to run task now: {e}")
            return False

    # ── 查询 ─────────────────────────────────────────────────

    def list_tasks(self) -> List[Dict]:
        """列出所有定时任务"""
        try:
            sql = "SELECT * FROM scheduled_tasks ORDER BY created_at DESC"
            tasks = self.mysql.execute_query(sql)

            # 补充 APScheduler 状态
            for task in tasks:
                job = self.scheduler.get_job(task["task_id"])
                task["next_run"] = str(job.next_run_time) if job and hasattr(job, 'next_run_time') else None
                task["is_running"] = bool(job) if job else False

            return tasks
        except Exception as e:
            self.logger.error(f"Failed to list tasks: {e}")
            return []

    def get_task(self, task_id: str) -> Optional[Dict]:
        """获取单个任务详情"""
        task = self._get_task_from_db(task_id)
        if task:
            job = self.scheduler.get_job(task_id)
            task["next_run"] = str(job.next_run_time) if job and hasattr(job, 'next_run_time') else None
            task["is_running"] = bool(job) if job else False

            # 获取最近执行日志
            log_sql = """
                SELECT * FROM sync_log
                WHERE table_name LIKE :pattern
                ORDER BY created_at DESC LIMIT 10
            """
            task["recent_logs"] = self.mysql.execute_query(
                log_sql, {"pattern": f"%{task_id}%"}
            )

        return task

    def _get_task_from_db(self, task_id: str) -> Optional[Dict]:
        """从数据库获取任务定义"""
        sql = "SELECT * FROM scheduled_tasks WHERE task_id = :task_id"
        results = self.mysql.execute_query(sql, {"task_id": task_id})
        return results[0] if results else None

    # ── 任务执行 ─────────────────────────────────────────────

    def _execute_task(self, task_id: str):
        """
        执行定时任务（由 APScheduler 触发）
        此方法在调度线程中运行
        """
        task = self._get_task_from_db(task_id)
        if not task:
            self.logger.warning(f"Task not found in DB: {task_id}")
            return

        start_time = datetime.now()
        self.logger.info(f"Executing task: [{task_id}] {task.get('name')}")

        try:
            task_type = task["task_type"]
            params = task.get("params", {})

            # 如果 params 是字符串，尝试解析 JSON
            if isinstance(params, str):
                import json
                try:
                    params = json.loads(params)
                except json.JSONDecodeError:
                    params = {}

            # 查找执行器
            executor_fn = self._executors.get(task_type)
            if executor_fn:
                result = executor_fn(params)
            else:
                result = {"status": "failed", "error": f"Unknown task_type: {task_type}"}

            status = result.get("status", "success")
            self.logger.info(
                f"Task [{task_id}] completed: {status} "
                f"(elapsed: {(datetime.now() - start_time).total_seconds():.1f}s)"
            )

        except Exception as e:
            status = "failed"
            result = {"status": "failed", "error": str(e)}
            self.logger.error(f"Task [{task_id}] failed: {e}", exc_info=True)

        # 更新任务状态
        self._update_task_status(task_id, status)
        # 记录执行日志
        self._log_execution(task_id, task.get("name", ""), status, result)

    def _execute_sync_api(self, params: Dict) -> Dict:
        """执行 API 同步任务"""
        if not self.sync_engine:
            return {"status": "failed", "error": "Sync engine not initialized"}
        return self.sync_engine.sync_from_api(
            api_url=params.get("api_url"),
            target_table=params.get("target_table"),
            sync_mode=params.get("sync_mode", "append"),
            headers=params.get("headers"),
            params=params.get("params"),
            pagination=params.get("pagination"),
        )

    def _execute_sync_csv(self, params: Dict) -> Dict:
        """执行 CSV 同步任务"""
        if not self.sync_engine:
            return {"status": "failed", "error": "Sync engine not initialized"}
        return self.sync_engine.sync_from_csv(
            file_path=params.get("file_path"),
            target_table=params.get("target_table"),
            sync_mode=params.get("sync_mode", "append"),
            encoding=params.get("encoding", "utf-8"),
        )

    def _update_task_status(self, task_id: str, status: str):
        """更新任务的上次执行状态"""
        try:
            sql = """
                UPDATE scheduled_tasks
                SET last_run = NOW(), last_status = :status
                WHERE task_id = :task_id
            """
            self.mysql.execute_update(sql, {"task_id": task_id, "status": status})
        except Exception as e:
            self.logger.warning(f"Failed to update task status: {e}")

    def _log_execution(self, task_id: str, task_name: str,
                       status: str, result: Dict):
        """记录任务执行日志"""
        try:
            sql = """
                INSERT INTO sync_log
                (table_name, total_rows, inserted_rows, sync_mode, source, status, created_at)
                VALUES (:table, :total, :inserted, :mode, :source, :status, NOW())
            """
            self.mysql.execute_update(sql, {
                "table": f"task:{task_id}:{task_name}",
                "total": result.get("total", 0),
                "inserted": result.get("inserted", 0),
                "mode": "scheduled",
                "source": task_id,
                "status": status,
            })
        except Exception as e:
            self.logger.warning(f"Failed to log execution: {e}")

    # ── 恢复 ─────────────────────────────────────────────────

    def _restore_tasks(self):
        """从数据库恢复所有已启用的定时任务"""
        try:
            tasks = self.list_tasks()
            restored = 0
            for task in tasks:
                if task.get("enabled") and task.get("task_type") in self._executors:
                    try:
                        params = task.get("params", {})
                        if isinstance(params, str):
                            import json
                            try:
                                params = json.loads(params)
                            except json.JSONDecodeError:
                                params = {}

                        self._add_job(
                            task["task_id"],
                            task["name"],
                            task["cron_expr"],
                            task["task_type"],
                            params,
                        )
                        restored += 1
                    except Exception as e:
                        self.logger.warning(
                            f"Failed to restore task [{task['task_id']}]: {e}"
                        )

            self.logger.info(f"Restored {restored}/{len(tasks)} tasks from database")
        except Exception as e:
            self.logger.error(f"Failed to restore tasks: {e}")
