-- ============================================
-- MySQL DataPilot 初始化脚本
-- 创建审计日志、定时任务、同步日志、数据血缘表
-- ============================================

CREATE DATABASE IF NOT EXISTS datapilot
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE datapilot;

-- ── 审计日志表 ──────────────────────────────

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    approval_id VARCHAR(64) NOT NULL COMMENT '审批 ID',
    operation VARCHAR(50) DEFAULT '' COMMENT '操作类型',
    sql_text TEXT COMMENT '执行的 SQL 语句',
    status VARCHAR(20) NOT NULL COMMENT '状态: success/failed/rejected/expired',
    affected_rows INT DEFAULT 0 COMMENT '影响行数',
    backup_id VARCHAR(64) DEFAULT NULL COMMENT '备份 ID（用于回滚）',
    error_msg VARCHAR(1000) DEFAULT NULL COMMENT '错误信息',
    user_id VARCHAR(64) DEFAULT NULL COMMENT '操作用户',
    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '执行时间',
    INDEX idx_approval_id (approval_id),
    INDEX idx_status (status),
    INDEX idx_executed_at (executed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='审计日志表 — 记录所有写操作的完整链路';

-- ── 同步日志表 ──────────────────────────────

CREATE TABLE IF NOT EXISTS sync_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    table_name VARCHAR(100) NOT NULL COMMENT '目标表名',
    total_rows INT DEFAULT 0 COMMENT '数据总行数',
    inserted_rows INT DEFAULT 0 COMMENT '实际写入行数',
    sync_mode VARCHAR(20) DEFAULT 'append' COMMENT '同步模式: append/upsert/replace',
    source VARCHAR(255) DEFAULT '' COMMENT '数据来源',
    status VARCHAR(20) DEFAULT 'success' COMMENT '同步状态',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '同步时间',
    INDEX idx_table_name (table_name),
    INDEX idx_created_at (created_at),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='数据同步日志表';

-- ── 定时任务表 ──────────────────────────────

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    task_id VARCHAR(32) PRIMARY KEY COMMENT '任务唯一 ID',
    name VARCHAR(100) NOT NULL COMMENT '任务名称',
    cron_expr VARCHAR(50) NOT NULL COMMENT 'Cron 表达式',
    task_type VARCHAR(20) NOT NULL COMMENT '任务类型: sync_api/sync_csv/etl/custom',
    params JSON DEFAULT NULL COMMENT '任务参数（JSON 格式）',
    enabled TINYINT DEFAULT 1 COMMENT '是否启用: 0=禁用 1=启用',
    last_run DATETIME DEFAULT NULL COMMENT '上次执行时间',
    last_status VARCHAR(20) DEFAULT NULL COMMENT '上次执行状态',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX idx_enabled (enabled),
    INDEX idx_type (task_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='定时任务定义表';

-- ── 数据血缘表 ──────────────────────────────

CREATE TABLE IF NOT EXISTS data_lineage (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    source_type VARCHAR(20) NOT NULL COMMENT '数据源类型: api/csv/json/table',
    source_name VARCHAR(255) NOT NULL COMMENT '数据源名称/URL/路径',
    target_table VARCHAR(100) NOT NULL COMMENT '目标表名',
    operation VARCHAR(50) NOT NULL COMMENT '操作: sync_append/sync_upsert/sync_replace/etl_transform',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX idx_source (source_type),
    INDEX idx_target (target_table),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='数据血缘追踪表';
