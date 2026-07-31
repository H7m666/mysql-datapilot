<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2>⏰ 定时任务</h2>
        <p class="page-subtitle">设置定时自动执行的数据同步任务，让数据自动保持最新</p>
      </div>
      <el-button type="primary" @click="showCreateDialog = true">+ 新建任务</el-button>
    </div>

    <el-table :data="tasks" style="width: 100%" v-loading="loading" stripe>
      <el-table-column prop="name" label="任务名称" min-width="160" />
      <el-table-column prop="task_type" label="任务类型" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="typeColor(row.task_type)">{{ typeLabel(row.task_type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="cron_expr" label="执行频率" width="150">
        <template #default="{ row }">
          <code>{{ row.cron_expr }}</code>
          <span style="font-size:12px;color:#999;margin-left:4px">{{ cronDesc(row.cron_expr) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="last_run" label="上次执行" width="170">
        <template #default="{ row }">
          <span v-if="row.last_run">{{ row.last_run }}</span>
          <span v-else style="color:#bbb">还没有执行过</span>
        </template>
      </el-table-column>
      <el-table-column prop="last_status" label="执行结果" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="row.last_status === 'success' ? 'success' : row.last_status === 'failed' ? 'danger' : 'info'">
            {{ row.last_status === 'success' ? '成功' : row.last_status === 'failed' ? '失败' : row.last_status || '未执行' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="开关" width="70">
        <template #default="{ row }">
          <el-switch :model-value="!!row.enabled" @change="(val: boolean) => toggleTask(row, val)" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click="runNow(row)">立即执行</el-button>
          <el-button size="small" text type="danger" @click="removeTask(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && tasks.length === 0" description="还没有定时任务，点击上方按钮创建第一个" />

    <!-- 创建任务对话框 -->
    <el-dialog v-model="showCreateDialog" title="新建定时任务" width="520px" top="10vh">
      <el-form :model="newTask" label-width="90px" label-position="left">
        <el-form-item label="任务名称">
          <el-input v-model="newTask.name" placeholder="例如：每日同步订单数据" />
        </el-form-item>
        <el-form-item label="任务类型">
          <el-select v-model="newTask.task_type" style="width:100%">
            <el-option label="从 API 接口同步数据" value="sync_api" />
            <el-option label="从 CSV 文件导入" value="sync_csv" />
          </el-select>
        </el-form-item>
        <el-form-item label="执行规律">
          <el-input v-model="newTask.cron_expr" placeholder="例如 0 9 * * *（每天上午9点执行）" />
        </el-form-item>

        <template v-if="newTask.task_type === 'sync_api'">
          <el-form-item label="API 地址">
            <el-input v-model="newTask.params.api_url" placeholder="https://api.xxx.com/data" />
          </el-form-item>
          <el-form-item label="写入哪个表">
            <el-input v-model="newTask.params.target_table" placeholder="目标表名" />
          </el-form-item>
        </template>

        <template v-if="newTask.task_type === 'sync_csv'">
          <el-form-item label="CSV 文件">
            <el-input v-model="newTask.params.file_path" placeholder="例如 /data/orders.csv" />
          </el-form-item>
          <el-form-item label="写入哪个表">
            <el-input v-model="newTask.params.target_table" placeholder="目标表名" />
          </el-form-item>
        </template>
      </el-form>

      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createNewTask">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listTasks, createTask, deleteTask, pauseTask, resumeTask, runTaskNow } from '@/api'
import type { TaskInfo } from '@/api'

const tasks = ref<TaskInfo[]>([])
const loading = ref(false)
const creating = ref(false)
const showCreateDialog = ref(false)
const newTask = ref({ name: '', task_type: 'sync_api', cron_expr: '', params: {} as Record<string, any> })

function typeColor(t: string) { return ({ sync_api: '', sync_csv: 'success' } as any)[t] || 'info' }
function typeLabel(t: string) { return ({ sync_api: 'API 同步', sync_csv: 'CSV 导入' } as any)[t] || t }

function cronDesc(cron: string) {
  const m: any = { '0 9 * * *': '每天9点', '0 2 * * *': '每天凌晨2点', '0 9 * * 1-5': '工作日9点', '*/30 * * * *': '每30分钟', '0 * * * *': '每小时', '0 0 1 * *': '每月1号' }
  return m[cron] || ''
}

async function fetchTasks() {
  loading.value = true
  try { const resp = await listTasks(); const raw = resp.data?.data || resp.data; tasks.value = Array.isArray(raw) ? raw : [] }
  catch (err: any) { ElMessage.error('获取任务列表失败') }
  finally { loading.value = false }
}

async function createNewTask() {
  if (!newTask.value.name || !newTask.value.cron_expr) { ElMessage.warning('请填写任务名称和执行规律'); return }
  creating.value = true
  try {
    await createTask({ name: newTask.value.name, task_type: newTask.value.task_type, cron_expr: newTask.value.cron_expr, params: newTask.value.params })
    ElMessage.success('任务创建成功')
    showCreateDialog.value = false
    newTask.value = { name: '', task_type: 'sync_api', cron_expr: '', params: {} }
    fetchTasks()
  } catch (err: any) { ElMessage.error('创建失败: ' + (err?.response?.data?.detail || err.message)) }
  finally { creating.value = false }
}

async function removeTask(task: TaskInfo) {
  try {
    await ElMessageBox.confirm(`确定删除「${task.name}」吗？`, '确认删除', { confirmButtonText: '确定删除', type: 'warning' })
    await deleteTask(task.task_id)
    ElMessage.success('已删除')
    fetchTasks()
  } catch { /* cancelled */ }
}

async function toggleTask(task: TaskInfo, on: boolean) {
  try {
    if (on) await resumeTask(task.task_id); else await pauseTask(task.task_id)
    ElMessage.success(on ? '已开启' : '已暂停')
    fetchTasks()
  } catch (err: any) { ElMessage.error('操作失败') }
}

async function runNow(task: TaskInfo) {
  try { await runTaskNow(task.task_id); ElMessage.success('已触发执行') }
  catch (err: any) { ElMessage.error('执行失败') }
}

onMounted(fetchTasks)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-header h2 { font-size: 20px; font-weight: 600; }
.page-subtitle { color: #999; font-size: 13px; margin-top: 2px; }
</style>
