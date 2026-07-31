# MySQL DataPilot — 简历包装方案

## 一、简历项目描述（直接可用）

### 版本 A：简洁版（适合一页简历，~120 字）

> **MySQL DataPilot — 基于 LangGraph 的 MySQL 智能数据管家** `2026.07`
> 
> 独立设计并开源的全链路 AI 数据管理平台，用自然语言驱动数据库操作。基于 **LangGraph ReAct Agent** 封装 12 个工具，实现「外部数据同步 → MySQL 内部 ETL → 智能查询」的数据闭环。
> 
> 核心工作：
> - 基于 **LangChain + LangGraph** 构建 ReAct Agent，集成 DeepSeek/OpenAI 多个 LLM，封装查表/建表/SQL 执行/数据同步/ETL 转换/定时调度等 12 个 Tool
> - 引入 **Human-in-the-Loop** 人工确认环 + SQL 防火墙 + 审计日志 + 自动回滚，AI 写操作需用户二次确认
> - 设计 **外部数据同步引擎**（API/CSV/JSON → MySQL），支持分页拉取、嵌套 JSON 解析、三种同步模式（append/upsert/replace）
> - 基于 **APScheduler** 实现定时任务调度，任务定义 **持久化到 MySQL**，支持暂停/恢复/手动触发
> - 后端 **FastAPI + SQLAlchemy 连接池**，前端 **Vue3 + TypeScript + ECharts** 血缘可视化
> 
> 技术栈：`Python` `LangChain/LangGraph` `FastAPI` `MySQL` `Vue3` `Docker` `APScheduler` `ECharts`

---

### 版本 B：详细版（适合两页简历或项目经历栏位充裕，~200 字）

> **MySQL DataPilot — 基于 LangGraph 的 MySQL 智能数据管家** `2026.07 — 至今`
> 
> 市面上大多数"AI + 数据库"项目只做 Text2SQL，本项目差异化定位为 **"同步优先"**——不只智能查询，还能主动从外部 API/CSV 拉取数据进 MySQL，形成完整数据管理闭环。已开源至 GitHub（⭐持续增长中）。
> 
> **技术实现：**
> - 基于 **LangGraph `create_react_agent`** 构建 ReAct Agent 核心决策引擎，自定义 12 个工具函数（get_schema、execute_query、sync_from_api、etl_transform、create_schedule 等），覆盖数据库全操作链路。LLM 通过 `checkpointer` 机制保持多轮对话上下文
> - 所有写操作（INSERT/UPDATE/DELETE/CREATE）必须经过 **Human-in-the-Loop 人工确认环**，使用 SQL 安全防火墙自动检测缺少 WHERE 的 UPDATE/DELETE 并拦截。执行前自动备份受影响数据，支持一键回滚
> - 自研 **外部数据同步引擎**：`requests` 拉取分页 REST API → `Pandas` 解析 CSV → 自动推断字段类型建表 → `SQLAlchemy` 批量写入 MySQL，支持 append/upsert/replace 三种同步模式
> - 基于 **APScheduler** 的定时调度模块，任务定义 **持久化到 MySQL 的 scheduled_tasks 表**（非内存存储），服务重启自动恢复。记录完整数据血缘链路（源→目标→查询）
> - 后端 **FastAPI + Pydantic 请求校验 + SQLAlchemy QueuePool** 连接池，前端 **Vue3 + Element Plus + ECharts** 力导向图。统一响应格式 `{code, data, msg}`，全局 trace_id 链路追踪
> 
> 技术栈：`Python 3.10+` `LangChain/LangGraph` `FastAPI` `SQLAlchemy` `MySQL 8.0` `Vue3` `TypeScript` `ECharts` `APScheduler` `Docker`

---

## 二、项目亮点提炼（面试时主动说）

| # | 亮点 | 面试官为什么感兴趣 |
| :--- | :--- | :--- |
| 1 | **12 个工具的 ReAct Agent** | LangChain 是 JD 高频词，你得展示不是只调 API，而是自己封装了复杂 Tool |
| 2 | **Human-in-the-Loop 审批 + SQL 防火墙** | 面试官最关心"AI 乱写 SQL 怎么办"，你有完整的安全方案 |
| 3 | **"同步优先"差异化** | 和市面上所有 Text2SQL 项目都不一样，面试官会觉得你有产品思维 |
| 4 | **APScheduler 持久化任务** | 大部分人的定时任务都是内存级别，你持久化到 MySQL + 自动恢复 |
| 5 | **开源 + 完整 README** | 说明你有工程化习惯，不是写个脚本就跑 |
| 6 | **v2.0 迭代（统一响应/trace_id）** | 证明你有重构和维护意识 |
| 7 | **FastAPI + 前后端分离** | 技术栈完整，显得不是只会 Python |

---

## 三、面试追问预判 & 标准回答

### Q1：LangGraph 的 ReAct Agent 你怎么实现的？

> 使用 LangGraph 的 `create_react_agent` 方法创建 Agent，传入了自定义的 12 个 Tool 函数。每个 Tool 用 `@tool` 装饰器注册，有明确的参数类型、docstring 描述和使用场景说明。Agent 会自动根据用户意图决策调用哪个工具。
> 
> 关键技术点：
> - `MemorySaver` 作为 checkpointer，通过 `thread_id` 保持多轮对话的上下文记忆
> - LLM 的 `temperature` 设为 0.1，保证 SQL 生成的准确性
> - `@tool` 的 docstring 里写了使用场景（比如 `execute_query` 写明只接受 SELECT），让 LLM 在决策时更有依据

### Q2：你怎么防止 AI 乱写 SQL 写坏数据的？

> 多层次防御：首先是 SQL 防火墙——在 `HITLManager` 里正则分析 SQL，拦截缺少 WHERE 的 UPDATE/DELETE、DROP、TRUNCATE 等危险操作并立即阻止。其次是人工确认环——所有写操作生成待审批卡片推送到前端，展示完整的 SQL 语句和预估影响行数，用户确认后才真正执行。最后是自动回滚——执行前把受影响的数据备份到 `_backup_{table}_{timestamp}` 表，出问题可以从审计日志找到 backup_id 恢复。

### Q3：你项目里的数据同步和其他人的"导入 CSV"有什么区别？

> 普通 CSV 导入就是读文件然后 insert，我的是完整的同步引擎：支持分页 API、嵌套 JSON 的 `json_path` 提取、自动根据数据类型推断建表字段、三种同步模式，而且写入了数据血缘追踪表，知道每张表的数据来源。

### Q4：为什么不用 LangChain 的 SQLDatabaseChain？

> SQLDatabaseChain 只能做 Text2SQL，功能单一。我用 LangGraph 的 `create_react_agent` 自定义了 12 个工具，让 Agent 不仅会查，还能主动同步数据、创建表、做 ETL、管理调度，形成 "数据进来 → 数据流转 → 数据出去" 的完整闭环。这是和市面上所有 Text2SQL 项目最大的区别。

---

## 四、简历技能标签建议

```
技术栈: Python / FastAPI / SQLAlchemy / LangChain / LangGraph / MySQL / Vue3 / TypeScript / ECharts / Docker
核心能力: LLM 应用开发 / ReAct Agent 工具编排 / 数据库操作与安全管理 / 前后端分离架构 / 开源项目维护
```

---

## 五、可选：加一行 GitHub 链接

```
📂 GitHub: https://github.com/H7m666/mysql-datapilot（已开源，⭐ xx）
```

> 建议放在简历项目描述的最后一行或页脚联系方式旁。
