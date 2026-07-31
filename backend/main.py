"""
MySQL DataPilot — FastAPI 后端入口 (v2.0)
"""

import os, json, uuid, time, logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv

from database import MySQLClient
from agent import MySQLAgent
from sync import ExternalSyncEngine
from scheduler import TaskScheduler
from models.schemas import (
    ChatRequest, SyncAPIRequest, SyncCSVRequest,
    TaskCreateRequest, ApprovalRequest, SQLExecuteRequest,
)

# ── 加载 .env ──
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# ── 日志 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("datapilot.log", encoding="utf-8")],
)
logger = logging.getLogger("datapilot")

# ── 全局服务 ──
mysql_client: Optional[MySQLClient] = None
agent: Optional[MySQLAgent] = None
sync_engine: Optional[ExternalSyncEngine] = None
scheduler: Optional[TaskScheduler] = None

# ── 可选 Token 鉴权 ──
API_TOKEN = os.getenv("API_TOKEN", "")
security = HTTPBearer(auto_error=False)

def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if not API_TOKEN:
        return True
    if not credentials or credentials.credentials != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid API Token")
    return True

# ── 初始化 ──
def init_services():
    global mysql_client, agent, sync_engine, scheduler
    logger.info(f"MySQL: {os.getenv('MYSQL_USER','root')}@{os.getenv('MYSQL_HOST','localhost')}:{os.getenv('MYSQL_PORT','3306')}/{os.getenv('MYSQL_DATABASE','datapilot')}")
    mysql_client = MySQLClient(
        host=os.getenv("MYSQL_HOST", "localhost"), port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"), password=os.getenv("MYSQL_PASSWORD", "root"),
        database=os.getenv("MYSQL_DATABASE", "datapilot"), pool_size=int(os.getenv("MYSQL_POOL_SIZE", "10")),
    )
    if not mysql_client.test_connection():
        logger.warning("⚠️ 数据库连接失败")
        return
    logger.info("✅ 数据库")
    sync_engine = ExternalSyncEngine(mysql_client)
    try:
        agent = MySQLAgent(mysql_client=mysql_client, sync_engine=sync_engine,
            model_name=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
            api_key=os.getenv("OPENAI_API_KEY"), api_base=os.getenv("OPENAI_API_BASE"))
        logger.info(f"✅ Agent ({os.getenv('LLM_MODEL','gpt-4o-mini')})")
    except Exception as e:
        logger.warning(f"⚠️ Agent 失败: {e}")
    scheduler = TaskScheduler(mysql_client, sync_engine)
    scheduler.start()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 启动...")
    init_services()
    logger.info("🎉 已就绪")
    yield
    if scheduler: scheduler.shutdown(wait=False)
    logger.info("👋 关闭")

# ── FastAPI ──
app = FastAPI(title="MySQL DataPilot API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.\d+\.\d+\.\d+)(:\d+)?",
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# ── 中间件 ──
@app.middleware("http")
async def add_trace_id(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4())[:8])
    request.state.trace_id = trace_id
    start = time.time()
    try:
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Elapsed"] = f"{(time.time() - start):.3f}s"
        return response
    except Exception as e:
        logger.error(f"[{trace_id}] Unhandled: {e}")
        return JSONResponse(status_code=500, content={"code": 500, "msg": str(e), "trace_id": trace_id})

@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"[{getattr(request.state, 'trace_id', '?')}] 422: {exc.errors()}")
    return JSONResponse(status_code=422, content={"code": 422, "msg": "请求参数校验失败", "detail": exc.errors()})

# ── 辅助 ──
def ok(data=None, msg="ok"): return {"code": 200, "data": data, "msg": msg}
def _chat_inner(message: str, session_id: str):
    if not agent: raise HTTPException(503, "Agent 未初始化")
    return agent.chat(message, session_id or "default")

# ── 对话 ──
@app.post("/api/chat")
async def chat_post(request: ChatRequest, _a=Depends(verify_token)):
    return ok(_chat_inner(request.message, request.session_id))

@app.get("/api/chat")
async def chat_get(message: str = Query(...), session_id: str = Query("default"), _a=Depends(verify_token)):
    return ok(_chat_inner(message, session_id))

@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    if not agent: raise HTTPException(503)
    return StreamingResponse(agent.chat_stream(request.message, request.session_id or "default"),
        media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ── 同步 ──
@app.post("/api/sync/api")
async def sync_api(request: SyncAPIRequest, _a=Depends(verify_token)):
    if not sync_engine: raise HTTPException(503)
    return ok(sync_engine.sync_from_api(request.api_url, request.target_table, request.sync_mode.value, request.headers, request.params, request.pagination))

@app.post("/api/sync/csv")
async def sync_csv(request: SyncCSVRequest, _a=Depends(verify_token)):
    if not sync_engine: raise HTTPException(503)
    return ok(sync_engine.sync_from_csv(request.file_path, request.target_table, request.sync_mode.value, request.encoding))

# ── 表结构 ──
@app.get("/api/schema")
async def schema(table_name: Optional[str] = Query(None)):
    if not mysql_client: raise HTTPException(503)
    return ok(mysql_client.get_table_schema(table_name) if table_name else mysql_client.get_all_table_schemas())

@app.get("/api/tables")
async def tables():
    if not mysql_client: raise HTTPException(503)
    return ok(mysql_client.get_database_info())

# ── 定时任务 ──
@app.get("/api/tasks")
async def list_tasks(): return ok(scheduler.list_tasks() if scheduler else [])

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    t = scheduler.get_task(task_id) if scheduler else None
    return ok(t) if t else HTTPException(404)

@app.post("/api/tasks")
async def create_task(request: TaskCreateRequest, _a=Depends(verify_token)):
    if not scheduler: raise HTTPException(503)
    return ok({"task_id": scheduler.create_task(request.name, request.cron_expr, request.task_type, request.params)})

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str, _a=Depends(verify_token)):
    if not scheduler or not scheduler.delete_task(task_id): raise HTTPException(404)
    return ok(msg="已删除")

@app.post("/api/tasks/{task_id}/{action}")
async def task_action(task_id: str, action: str, _a=Depends(verify_token)):
    if not scheduler: raise HTTPException(503)
    m = {"pause": scheduler.pause_task, "resume": scheduler.resume_task, "run": scheduler.run_task_now}
    if action not in m: raise HTTPException(400)
    return ok() if m[action](task_id) else HTTPException(404)

# ── 审批 ──
@app.get("/api/approvals")
async def approvals(): return ok(agent.get_pending_approvals() if agent else [])

@app.post("/api/approvals/{approval_id}")
async def handle_approval(approval_id: str, request: ApprovalRequest, _a=Depends(verify_token)):
    if not agent: raise HTTPException(503)
    return ok(agent.handle_approval(approval_id, request.action.value, request.edited_sql))

# ── 审计 & 日志 ──
@app.get("/api/audit")
async def audit(limit: int = Query(100, ge=1, le=1000), status: Optional[str] = Query(None)):
    if not agent: raise HTTPException(503)
    logs = agent.hitl.get_audit_logs(limit, status)
    return ok({"count": len(logs), "logs": logs})

@app.get("/api/sync/logs")
async def sync_logs(limit: int = Query(50, ge=1, le=500)):
    return ok(sync_engine.get_sync_logs(limit) if sync_engine else [])

# ── 血缘 ──
@app.get("/api/lineage")
async def lineage(table_name: Optional[str] = Query(None)):
    if not mysql_client: raise HTTPException(503)
    if table_name:
        return ok(mysql_client.execute_query("SELECT * FROM data_lineage WHERE source_name LIKE :n OR target_table=:t ORDER BY created_at DESC", {"n": f"%{table_name}%", "t": table_name}))
    return ok(mysql_client.execute_query("SELECT * FROM data_lineage ORDER BY created_at DESC LIMIT 200"))

# ── SQL 执行 ──
MAX_QUERY_ROWS = 1000

@app.post("/api/sql/execute")
async def sql_execute(request: SQLExecuteRequest, _a=Depends(verify_token)):
    if not mysql_client: raise HTTPException(503)
    sql = request.sql.strip().rstrip(";")
    if sql.upper().startswith("SELECT"):
        if "LIMIT" not in sql.upper(): sql += f" LIMIT {MAX_QUERY_ROWS}"
        return ok({"rows": mysql_client.execute_query(sql), "row_count": "?"})
    if not agent: raise HTTPException(503)
    a = agent.hitl.analyze_sql(sql)
    if not request.requires_approval:
        return ok({"affected_rows": mysql_client.execute_update(sql)})
    return ok(agent.hitl.request_approval("手动 SQL", sql, a.get("estimated_affected_rows", 0)))

@app.post("/api/sql/validate")
async def sql_validate(request: SQLExecuteRequest):
    return ok(agent.hitl.analyze_sql(request.sql) if agent else {})

# ── 配置 ──
@app.get("/api/config")
async def config():
    return ok({"database": {"host": os.getenv("MYSQL_HOST","localhost"), "port": int(os.getenv("MYSQL_PORT","3306")), "database": os.getenv("MYSQL_DATABASE","datapilot"), "user": os.getenv("MYSQL_USER","root")}, "llm": {"model": os.getenv("LLM_MODEL","gpt-4o-mini"), "base": os.getenv("OPENAI_API_BASE","")}})

# ── 回滚 ──
@app.post("/api/rollback/{backup_id}")
async def rollback(backup_id: str, _a=Depends(verify_token)):
    if not agent: raise HTTPException(503)
    return ok(agent.rollback_operation(backup_id))

# ── 健康 & 根 ──
@app.get("/api/health")
async def health():
    return {"status": "ok", "database": mysql_client.test_connection() if mysql_client else False}

@app.get("/")
async def root(): return {"name": "MySQL DataPilot", "version": "2.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT","8000")), reload=os.getenv("ENV","production")=="development")
