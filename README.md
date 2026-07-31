# MySQL DataPilot 🛫

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-green.svg)](https://www.python.org/)
[![Vue](https://img.shields.io/badge/vue-3.x-brightgreen.svg)](https://vuejs.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-ReAct-orange.svg)](https://langchain.com/)

> **Most MySQL + LLM projects answer questions. This one fetches the data first, then answers.**

市面上 90% 的"数据库+大模型"项目只做 Text2SQL——假设数据已经在库里。但现实是：**数据不在库里，在 API 里、在 CSV 里、在别人的系统里**。

MySQL DataPilot 不只"查"，更会"搬"：

✨ **用自然语言驱动数据同步** —— "把 https://api.example.com/orders 的数据同步到 order_table"

🔒 **生产级安全保障** —— 所有写操作须人工确认 (HITL) + 审计日志 + 自动回滚

🧠 **LangGraph ReAct Agent** —— 12 个工具，覆盖查/增/改/建/同步/ETL/调度全链路

🚀 **命令行一键启动** —— 装好依赖直接跑，前后端分离

## 与同类项目的区别

| 对比维度 | 主流项目 (Vanna/Chat2DB/DB-GPT) | MySQL DataPilot |
| :--- | :--- | :--- |
| **核心能力** | 仅 Text2SQL（自然语言→查询） | 查询 + 同步 + ETL + 调度 全链路 |
| **数据来源** | 假设数据已在库里 | 主动从 API/CSV 拉取数据进 MySQL |
| **写操作** | 无或高风险 | 人工确认环 (HITL) + 审计日志 |
| **任务调度** | 无 | APScheduler 定时同步 + 持久化 |
| **数据血缘** | 无 | 完整记录"源→目标→查询"链路 |
| **安全机制** | 依赖用户自觉 | SQL 防火墙 + 二次确认 + 回滚预案 |

## 架构总览

```
┌──────────────────────────────────────────────────────────┐
│              前端 (Vue3 + Vite + TypeScript)              │
│        对话界面 / 定时任务 / 数据地图(ECharts) / 操作记录   │
└──────────────────────────────────────────────────────────┘
                           │ HTTP
┌──────────────────────────────────────────────────────────┐
│                后端 (Python 3.10+ / FastAPI)              │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │     LangGraph ReAct Agent（核心决策引擎）          │  │
│  │  12 个工具: 查表/生成SQL/验证/执行/同步/建表/      │  │
│  │            ETL/调度/审计...                        │  │
│  └────────────────────────────────────────────────────┘  │
│           │              │                 │              │
│  ┌────────┴──────┐ ┌─────┴──────┐ ┌──────┴───────────┐  │
│  │ 数据同步引擎   │ │ MySQL 内部 │ │ 定时调度引擎      │  │
│  │ API/CSV→MySQL │ │ ETL 引擎   │ │ APScheduler       │  │
│  └───────────────┘ └────────────┘ └──────────────────┘  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │     安全与审计层                                     │  │
│  │  SQL防火墙 | HITL人工确认 | 审计日志 | 自动回滚     │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │  MySQL (8.0)    │
                  │  SQLAlchemy ORM │
                  └─────────────────┘
```

## Quick Start

### 前置条件
- Python 3.10+
- Node.js 18+ / npm
- MySQL 8.0

### 1. 克隆并配置

```bash
git clone https://github.com/yourname/mysql-datapilot.git
cd mysql-datapilot
cp .env.example .env
# 编辑 .env，填入你的 MySQL 连接信息和 LLM API Key
```

### 2. 初始化数据库

```bash
mysql -u root -p < init.sql
```

### 3. 启动后端

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

### 4. 启动前端（新终端）

```bash
cd frontend
npm install
npm run dev
```

### 5. 访问
- 🖥️ **前端界面**: http://localhost:5173
- 📖 **API 文档**: http://localhost:8000/docs

## 项目结构

```
mysql-datapilot/
├── backend/
│   ├── main.py                 # FastAPI 入口 + 所有 API 路由
│   ├── database/
│   │   ├── __init__.py
│   │   └── mysql_client.py     # MySQL 统一操作层 (SQLAlchemy + pymysql)
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── agent.py            # LangGraph ReAct Agent (12 个 Tool)
│   │   └── hitl.py             # Human-in-the-Loop 审批管理器
│   ├── sync/
│   │   ├── __init__.py
│   │   └── sync_engine.py      # 外部数据同步引擎 (API/CSV/JSON → MySQL)
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── scheduler.py        # APScheduler 定时调度引擎
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py          # Pydantic 请求/响应模型
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── views/
│   │   │   ├── Chat.vue        # AI 助手对话页面
│   │   │   ├── Tasks.vue       # 定时任务管理
│   │   │   ├── Lineage.vue     # 数据地图 (ECharts 力导向图)
│   │   │   └── Audit.vue       # 操作记录
│   │   ├── api/index.ts        # API 请求层 (Axios)
│   │   ├── router/index.ts     # 路由配置
│   │   ├── styles/global.css   # 全局样式
│   │   ├── App.vue
│   │   └── main.ts
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig.json
├── init.sql                    # 数据库初始化 DDL (4 张管理表)
├── .env.example                # 环境变量模板
├── .gitignore
├── LICENSE                     # MIT
└── README.md
```

## 核心功能

### 🤖 AI 智能助手
用自然语言管理数据库，Agent 自动获取表结构、生成并验证 SQL、执行查询。支持多轮对话上下文记忆。

### 🔄 外部数据同步
支持从 RESTful API、CSV、JSON 文件拉取数据到 MySQL，支持分页/认证/嵌套解析，三种同步模式 (append/upsert/replace)。

### 🔒 安全审批机制
所有写操作须人工确认：Agent 生成 SQL → SQL 防火墙检查 → 前端展示待审批卡片 → 用户确认/拒绝/编辑 → 执行 + 审计日志。UPDATE/DELETE 自动备份数据支持回滚。

### ⏰ 定时任务调度
Cron 表达式配置定时同步/ETL 任务，任务定义持久化到 MySQL，支持暂停/恢复/手动触发/执行日志追踪。

### 🗺️ 数据地图
自动记录数据流转链路，ECharts 力导向图可视化展示"数据源 → MySQL 表 → 下游"的血缘关系。

### 📝 操作记录
完整记录所有写操作的时间、SQL、状态、影响行数、备份 ID，支持按状态筛选。

## Agent 工具集

| # | 工具名 | 功能 | 安全级别 |
| :--- | :--- | :--- | :--- |
| 1 | `get_schema` | 获取表结构信息 | 只读 |
| 2 | `list_tables` | 列出所有表及行数 | 只读 |
| 3 | `get_database_info` | 获取数据库概况 | 只读 |
| 4 | `validate_sql` | SQL 安全验证 | 只读 |
| 5 | `execute_query` | 执行 SELECT 查询 | 只读 |
| 6 | `get_audit_logs` | 查看审计日志 | 只读 |
| 7 | `execute_write` | 执行写操作 | 需审批 |
| 8 | `create_table` | 创建新表 | 需审批 |
| 9 | `sync_from_api` | 从 REST API 同步数据 | 需审批 |
| 10 | `sync_from_csv` | 从 CSV 文件导入数据 | 需审批 |
| 11 | `etl_transform` | ETL 表到表转换 | 需审批 |
| 12 | `generate_sql` | 根据需求生成 SQL | 辅助工具 |

## LLM 配置

支持所有 OpenAI 兼容 API，修改 `.env` 中的三个变量即可切换：

| 厂商 | OPENAI_API_BASE | LLM_MODEL |
| :--- | :--- | :--- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| API 中转站 | 你的中转地址 | 对应模型名 |

## 技术栈

**后端**: Python 3.10+ · FastAPI · LangChain + LangGraph (ReAct Agent) · SQLAlchemy + PyMySQL · APScheduler · Pandas

**前端**: Vue 3 · TypeScript · Vite · Element Plus · ECharts · Marked + Highlight.js

**数据库**: MySQL 8.0

## License

MIT © MySQL DataPilot Contributors
