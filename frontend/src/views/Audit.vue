<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2>📝 操作记录</h2>
        <p class="page-subtitle">每次对数据库的修改操作都在这里留档，可以随时查看和回滚</p>
      </div>
      <div class="header-right">
        <el-select v-model="statusFilter" placeholder="筛选状态" clearable style="width:130px" @change="loadLogs">
          <el-option label="全部" value="" />
          <el-option label="✅ 成功" value="success" />
          <el-option label="❌ 失败" value="failed" />
          <el-option label="🚫 已拒绝" value="rejected" />
        </el-select>
        <el-button text @click="loadLogs">刷新</el-button>
      </div>
    </div>

    <el-table :data="logs" style="width: 100%" v-loading="loading" stripe max-height="calc(100vh - 160px)">
      <el-table-column label="时间" width="170">
        <template #default="{ row }">{{ row.executed_at || row.created_at }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="statusTag(row.status)">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="SQL 语句" min-width="350">
        <template #default="{ row }">
          <div style="font-size:12px; word-break:break-all; max-width:400px">
            <code>{{ (row.sql_text || '').slice(0, 200) }}{{ (row.sql_text || '').length > 200 ? '...' : '' }}</code>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="affected_rows" label="影响行数" width="90" align="center" />
      <el-table-column prop="backup_id" label="能否回滚" width="100">
        <template #default="{ row }">
          <span v-if="row.backup_id && row.status === 'success'" style="color:#67C23A">✅ 可回滚</span>
          <span v-else style="color:#bbb">不需要</span>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && logs.length === 0" description="还没有操作记录" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getAuditLogs } from '@/api'

const logs = ref<any[]>([])
const loading = ref(false)
const statusFilter = ref('')

function statusTag(s: string) {
  return { success: 'success', executed: 'success', failed: 'danger', rejected: 'warning', expired: 'info' }[s] || 'info'
}
function statusText(s: string) {
  return { success: '成功', executed: '成功', failed: '失败', rejected: '已拒绝', expired: '已过期', pending: '待批准' }[s] || s
}

async function loadLogs() {
  loading.value = true
  try {
    const resp = await getAuditLogs(200, statusFilter.value || undefined); const data = resp.data?.data || resp.data
    logs.value = data.logs || data as any[] || []
  } catch (err: any) { ElMessage.error('加载失败') }
  finally { loading.value = false }
}

onMounted(loadLogs)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-header h2 { font-size: 20px; font-weight: 600; }
.page-subtitle { color: #999; font-size: 13px; margin-top: 2px; }
.header-right { display: flex; gap: 8px; align-items: center; }
</style>
