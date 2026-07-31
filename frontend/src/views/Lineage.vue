<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2>🗺️ 数据地图</h2>
        <p class="page-subtitle">追踪数据从哪来、到哪去 —— 一眼看清数据流向</p>
      </div>
      <el-input v-model="filterTable" placeholder="搜索表名..." clearable style="width:220px" @input="loadLineage">
        <template #prefix>🔍</template>
      </el-input>
    </div>

    <div class="chart-box" ref="chartRef">
      <el-empty v-if="!hasData" description="还没有数据记录，执行数据同步后这里会自动生成数据流向图" />
    </div>

    <div v-if="records.length > 0" style="margin-top:20px">
      <h3 style="margin-bottom:12px">数据来源记录</h3>
      <el-table :data="records" size="small" stripe>
        <el-table-column prop="created_at" label="时间" width="170" />
        <el-table-column label="从哪里来" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.source_type === 'api' ? '' : row.source_type === 'csv' ? 'success' : 'info'">
              {{ row.source_type === 'api' ? 'API 接口' : row.source_type === 'csv' ? 'CSV 文件' : row.source_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="source_name" label="来源地址" min-width="200">
          <template #default="{ row }">
            <span style="font-size:13px">{{ row.source_name?.replace(/^(api|csv):/, '') }}</span>
          </template>
        </el-table-column>
        <el-table-column label="箭头" width="60" align="center"><template #default>→</template></el-table-column>
        <el-table-column prop="target_table" label="存到哪张表" width="150">
          <template #default="{ row }">
            <el-tag size="small" type="success">{{ row.target_table }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { getLineage } from '@/api'
import * as echarts from 'echarts'

const filterTable = ref('')
const records = ref<any[]>([])
const hasData = ref(false)
const chartRef = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

async function loadLineage() {
  try {
    const resp = await getLineage(filterTable.value || undefined); const data = resp.data?.data || resp.data
    records.value = (Array.isArray(data) ? data : data as any[]) || []
    hasData.value = records.value.length > 0
    if (hasData.value) { await nextTick(); drawChart() }
  } catch { records.value = []; hasData.value = false }
}

function drawChart() {
  if (!chartRef.value || !hasData.value) return
  if (!chart) chart = echarts.init(chartRef.value)

  const nodes: any[] = [], links: any[] = [], nameSet = new Set<string>()
  for (const r of records.value) {
    const src = r.source_name?.replace(/^(api|csv|json):/, '')?.slice(0, 30) || r.source_name
    if (!nameSet.has(src)) { nodes.push({ name: src, category: 0, symbolSize: 40 }); nameSet.add(src) }
    if (!nameSet.has(r.target_table)) { nodes.push({ name: r.target_table, category: 1, symbolSize: 50 }); nameSet.add(r.target_table) }
    links.push({ source: src, target: r.target_table, label: { show: true, formatter: r.operation || 'sync', fontSize: 10 } })
  }

  chart.setOption({
    tooltip: { formatter: (p: any) => p.dataType === 'edge' ? `${p.data.source} → ${p.data.target}` : p.data.name },
    series: [{
      type: 'graph', layout: 'force', roam: true,
      categories: [{ name: '数据来源' }, { name: 'MySQL 表' }],
      nodes, edges: links,
      force: { repulsion: 200, edgeLength: [150, 300] },
      label: { show: true, fontSize: 11 },
      lineStyle: { curveness: 0.3 },
    }],
  })
  window.addEventListener('resize', () => chart?.resize())
}

onMounted(loadLineage)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-header h2 { font-size: 20px; font-weight: 600; }
.page-subtitle { color: #999; font-size: 13px; margin-top: 2px; }
.chart-box { width: 100%; height: 450px; background: #fff; border-radius: 8px; border: 1px solid var(--border-color); }
</style>
