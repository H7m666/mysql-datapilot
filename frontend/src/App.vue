<template>
  <div class="app-layout">
    <!-- 侧边栏 -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <span class="logo-icon">🛫</span>
        <span class="logo-text">MySQL DataPilot</span>
      </div>

      <nav class="sidebar-nav">
        <router-link
          v-for="route in navRoutes"
          :key="route.path"
          :to="route.path"
          class="nav-item"
          active-class="nav-item--active"
        >
          <el-icon><component :is="route.meta.icon" /></el-icon>
          <span>{{ route.meta.title }}</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <div class="status-indicator">
          <span class="status-dot" :class="connected ? 'connected' : 'disconnected'" />
          <span class="status-text">{{ connected ? '已连接' : '未连接' }}</span>
        </div>
        <div class="version-text">v1.0.0</div>
      </div>
    </aside>

    <!-- 主内容区 -->
    <div class="main-area">
      <router-view />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { healthCheck } from '@/api'

const router = useRouter()
const connected = ref(false)

const navRoutes = router.options.routes.filter((r) => r.path !== '/')

onMounted(async () => {
  try {
    await healthCheck()
    connected.value = true
  } catch {
    connected.value = false
  }
})
</script>

<style scoped>
.sidebar-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}
.logo-icon { font-size: 24px; }
.logo-text { font-size: 16px; font-weight: 700; letter-spacing: 0.5px; }

.sidebar-nav {
  flex: 1;
  padding: 12px 0;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 20px;
  color: var(--sidebar-text);
  text-decoration: none;
  font-size: 14px;
  transition: all 0.2s;
  border-left: 3px solid transparent;
  margin: 2px 0;
}
.nav-item:hover {
  background: rgba(255,255,255,0.06);
}
.nav-item--active {
  background: rgba(64,158,255,0.15);
  color: var(--sidebar-active);
  border-left-color: var(--sidebar-active);
}

.sidebar-footer {
  padding: 16px;
  border-top: 1px solid rgba(255,255,255,0.08);
}
.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.status-dot.connected { background: var(--success); }
.status-dot.disconnected { background: var(--danger); }
.status-text { font-size: 12px; color: var(--text-secondary); }
.version-text { font-size: 11px; color: rgba(255,255,255,0.3); }
</style>
