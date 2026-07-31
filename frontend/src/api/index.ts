/**
 * API 请求层 — 封装所有后端接口调用
 */
import axios, { AxiosResponse } from 'axios'

const api = axios.create({
  baseURL: 'http://127.0.0.1:8000/api',
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
})

// ── 响应拦截器 ─────────────────────────────
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const msg = error.response?.data?.detail || error.message || '请求失败'
    console.error('[API Error]', msg)
    return Promise.reject(error)
  }
)

// ── 类型定义 ───────────────────────────────

export interface ChatResponse {
  response: string
  session_id?: string
  pending_approval?: ApprovalInfo | null
  timestamp: string
}

export interface ApprovalInfo {
  id: string
  operation: string
  sql: string
  estimated_rows: number
  context: Record<string, any>
  status: string
  created_at: string
}

export interface SyncResult {
  status: string
  table?: string
  total: number
  inserted: number
  sync_mode?: string
  message?: string
  batch_id?: string
  timestamp: string
}

export interface TaskInfo {
  task_id: string
  name: string
  cron_expr: string
  task_type: string
  params: any
  enabled: number | boolean
  last_run: string | null
  last_status: string | null
  next_run: string | null
  is_running: boolean
  created_at: string
}

export interface TableSchema {
  database?: string
  tables?: string[]
  table_count?: number
  table?: string
  columns?: ColumnDef[]
  primary_key?: string[]
}

export interface ColumnDef {
  name: string
  type: string
  nullable: boolean
  default?: string
  comment?: string
}

// ── 对话 ────────────────────────────────────

export async function sendMessage(message: string, sessionId?: string) {
  try {
    const response = await api.post('/chat', { message, session_id: sessionId })
    return response
  } catch (error: any) {
    console.error('sendMessage error:', error?.response?.data || error?.message || error)
    return null
  }
}

export function sendMessageStream(message: string, sessionId?: string) {
  const params = new URLSearchParams()
  // SSE stream not through axios; handled in component
  return fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
  })
}

// ── 数据同步 ────────────────────────────────

export function syncFromAPI(params: {
  api_url: string
  target_table: string
  sync_mode?: string
  headers?: Record<string, string>
  params?: Record<string, any>
}) {
  return api.post<SyncResult>('/sync/api', params)
}

export function syncFromCSV(params: {
  file_path: string
  target_table: string
  sync_mode?: string
  encoding?: string
}) {
  return api.post<SyncResult>('/sync/csv', params)
}

// ── 表结构 ──────────────────────────────────

export function getSchema(tableName?: string) {
  const params = tableName ? { table_name: tableName } : {}
  return api.get<TableSchema>('/schema', { params })
}

export function listTables() {
  return api.get('/tables')
}

// ── 定时任务 ────────────────────────────────

export function listTasks() {
  return api.get<TaskInfo[]>('/tasks')
}

export function getTask(taskId: string) {
  return api.get<TaskInfo>(`/tasks/${taskId}`)
}

export function createTask(params: {
  name: string
  cron_expr: string
  task_type: string
  params: Record<string, any>
}) {
  return api.post('/tasks', params)
}

export function deleteTask(taskId: string) {
  return api.delete(`/tasks/${taskId}`)
}

export function pauseTask(taskId: string) {
  return api.post(`/tasks/${taskId}/pause`)
}

export function resumeTask(taskId: string) {
  return api.post(`/tasks/${taskId}/resume`)
}

export function runTaskNow(taskId: string) {
  return api.post(`/tasks/${taskId}/run`)
}

// ── 审批 ────────────────────────────────────

export function getPendingApprovals() {
  return api.get<ApprovalInfo[]>('/approvals')
}

export function handleApproval(approvalId: string, action: 'approve' | 'reject' | 'edit', editedSql?: string) {
  return api.post(`/approvals/${approvalId}`, {
    approval_id: approvalId,
    action,
    edited_sql: editedSql,
  })
}

// ── 审计日志 ────────────────────────────────

export function getAuditLogs(limit = 100, status?: string) {
  return api.get('/audit', { params: { limit, status } })
}

// ── SQL 执行 ────────────────────────────────

export function executeSQL(sql: string, requiresApproval = true) {
  return api.post('/sql/execute', { sql, requires_approval: requiresApproval })
}

export function validateSQL(sql: string) {
  return api.post('/sql/validate', { sql })
}

// ── 数据血缘 ────────────────────────────────

export function getLineage(tableName?: string) {
  return api.get('/lineage', { params: { table_name: tableName } })
}

// ── 同步日志 ────────────────────────────────

export function getSyncLogs(limit = 50) {
  return api.get('/sync/logs', { params: { limit } })
}

// ── 健康检查 ────────────────────────────────

export function healthCheck() {
  return api.get('/health')
}

export default api
