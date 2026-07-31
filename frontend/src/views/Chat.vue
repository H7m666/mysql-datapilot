<template>
  <div class="page-container">
    <div class="page-header">
      <h2>🤖 AI 数据助手</h2>
      <p class="page-subtitle">用大白话告诉 AI 你想对数据做什么 — 查数据、导数据、做报表，都可以</p>
    </div>

    <!-- 快速入口卡片 -->
    <div class="quick-cards" v-if="messages.length === 0">
      <div class="quick-card" @click="sendQuickPrompt('📊 帮我看看数据库里有哪些表？每张表有多少数据？')">
        <span class="card-icon">📊</span>
        <span class="card-title">查看数据库概况</span>
        <span class="card-desc">数据库里有哪些表？每张表有多少条数据？</span>
      </div>
      <div class="quick-card" @click="sendQuickPrompt('🔍 帮我看一下所有表的表结构，有哪些字段')">
        <span class="card-icon">🔍</span>
        <span class="card-title">查看表结构</span>
        <span class="card-desc">每张表有哪些字段？字段类型是什么？</span>
      </div>
      <div class="quick-card" @click="sendQuickPrompt('✨ 帮我创建一张员工表 employee，包含 id、姓名、部门、入职日期')">
        <span class="card-icon">✨</span>
        <span class="card-title">创建新表</span>
        <span class="card-desc">用自然语言描述，AI 自动生成建表语句</span>
      </div>
      <div class="quick-card" @click="sendQuickPrompt('📋 帮我查看最近的数据库操作记录')">
        <span class="card-icon">📋</span>
        <span class="card-title">查看操作记录</span>
        <span class="card-desc">谁在什么时候对数据库做了什么操作？</span>
      </div>
    </div>

    <!-- 消息列表 -->
    <div class="message-list" ref="messageListRef">
      <div
        v-for="msg in messages"
        :key="msg.id"
        :class="['message', msg.role]"
      >
        <div class="avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
        <div class="content">
          <div
            v-if="msg.role === 'assistant'"
            class="markdown-body"
            v-html="renderMarkdown(msg.content)"
          />
          <div v-else>{{ msg.content }}</div>

          <!-- 待审批卡片 -->
          <div v-if="msg.pendingApproval" class="approval-card">
            <div class="approval-title">
              ⚠️ <strong>以下操作需要你确认后才能执行</strong>
            </div>
            <div class="approval-info">
              <div class="approval-row">
                <span class="label">操作内容：</span>
                <span>{{ msg.pendingApproval.operation }}</span>
              </div>
              <div class="approval-row">
                <span class="label">预计影响：</span>
                <span>{{ msg.pendingApproval.estimated_rows ?? 0 }} 行数据</span>
              </div>
            </div>
            <div class="sql-box">
              <code>{{ msg.pendingApproval.sql }}</code>
            </div>
            <div v-if="msg.pendingApproval.analysis?.warnings?.length" class="warn-box">
              <div v-for="w in msg.pendingApproval.analysis.warnings" :key="w">{{ w }}</div>
            </div>
            <div class="btn-group">
              <el-button type="success" size="small" @click="approve(msg.pendingApproval.id, msg.id)">✅ 确认执行</el-button>
              <el-button type="danger" size="small" @click="reject(msg.pendingApproval.id, msg.id)">❌ 取消</el-button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="loading" class="message assistant">
        <div class="avatar">🤖</div>
        <div class="content"><span class="dot-pulse">思考中</span></div>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="input-area">
      <div class="input-wrapper">
        <input
          v-model="inputMessage"
          class="chat-input"
          placeholder="告诉 AI 你想做什么，比如：查一下订单表里今天有多少条数据"
          :disabled="loading"
          @keydown.enter="sendMessage"
        />
        <el-button
          type="primary"
          :loading="loading"
          :disabled="!inputMessage.trim()"
          @click="sendMessage"
          class="send-btn"
        >
          发送
        </el-button>
      </div>
      <div class="input-tip">按 Enter 发送，用大白话描述需求即可</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import hljs from 'highlight.js'
import axios from 'axios'
import { handleApproval, type ApprovalInfo } from '@/api'

// ── Markdown 渲染 ────────────────────────────

marked.setOptions({ breaks: true, gfm: true })

function renderMarkdown(text: string): string {
  if (!text) return ''
  try {
    return marked.parse(text) as string
  } catch {
    return text
  }
}

// ── 消息 ──────────────────────────────────────

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  pendingApproval?: ApprovalInfo | null
  timestamp: string
}

const messages = ref<Message[]>([])
const inputMessage = ref('')
const loading = ref(false)
const messageListRef = ref<HTMLElement | null>(null)
const sessionId = ref(`session_${Date.now()}_${Math.random().toString(36).slice(2,6)}`)

function genId() { return `m_${Date.now()}_${Math.random().toString(36).slice(2,6)}` }

function scrollBottom() {
  nextTick(() => {
    if (messageListRef.value) {
      messageListRef.value.scrollTop = messageListRef.value.scrollHeight
    }
  })
}

// ── 发送 ──────────────────────────────────────

async function doSend(text: string) {
  const t = text.trim()
  if (!t || loading.value) return

  messages.value.push({ id: genId(), role: 'user', content: t, timestamp: new Date().toISOString() })
  inputMessage.value = ''
  scrollBottom()
  loading.value = true

  try {
    const result = await axios.post('http://127.0.0.1:8000/api/chat', { message: t, session_id: sessionId.value }, { timeout: 120000 })
    if (!result || !result.data || !result.data.data) {
      messages.value.push({ id: genId(), role: 'assistant', content: '❌ 请求失败：服务器无响应', timestamp: new Date().toISOString() })
      return
    }
    // v2.0 格式: { code:200, data:{ response:..., ... } }
    const resp = result.data.data
    messages.value.push({
      id: genId(),
      role: 'assistant',
      content: resp.response,
      pendingApproval: resp.pending_approval || null,
      timestamp: resp.timestamp,
    })
  } catch (err: any) {
    console.error('Chat error:', err?.message || err)
    messages.value.push({
      id: genId(),
      role: 'assistant',
      content: '❌ 请求失败：' + (err?.response?.data?.detail || err.message),
      timestamp: new Date().toISOString(),
    })
  } finally {
    loading.value = false
    scrollBottom()
  }
}

function sendMessage() { doSend(inputMessage.value) }
function sendQuickPrompt(p: string) { doSend(p) }

// ── 审批 ──────────────────────────────────────

async function approve(approvalId: string, msgId: string) {
  try {
    const resp = await handleApproval(approvalId, 'approve'); const data = resp.data?.data || resp.data
    messages.value.push({
      id: genId(), role: 'assistant',
      content: `✅ 操作已完成，影响了 ${data.affected_rows ?? 0} 行。`,
      timestamp: new Date().toISOString(),
    })
    const m = messages.value.find(x => x.id === msgId)
    if (m) m.pendingApproval = null
  } catch (err: any) {
    ElMessage.error('执行失败: ' + (err?.response?.data?.detail || err.message))
  }
  scrollBottom()
}

async function reject(approvalId: string, msgId: string) {
  try {
    await handleApproval(approvalId, 'reject')
    messages.value.push({
      id: genId(), role: 'assistant',
      content: '🚫 已取消，没有对数据库做任何更改。',
      timestamp: new Date().toISOString(),
    })
    const m = messages.value.find(x => x.id === msgId)
    if (m) m.pendingApproval = null
  } catch (err: any) {
    ElMessage.error('操作失败: ' + (err?.response?.data?.detail || err.message))
  }
  scrollBottom()
}
</script>

<style scoped>
.page-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  max-width: 900px;
  margin: 0 auto;
  padding: 0 20px;
}

.page-header {
  padding: 24px 0 4px;
  text-align: center;
  flex-shrink: 0;
}
.page-header h2 { font-size: 22px; font-weight: 700; }
.page-subtitle { color: var(--text-secondary); font-size: 14px; margin-top: 4px; }

/* ── 快速入口卡片 ─────────────────────── */
.quick-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  padding: 16px 0 20px;
  flex-shrink: 0;
}
.quick-card {
  background: var(--bg-white);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s;
}
.quick-card:hover { border-color: var(--primary); box-shadow: 0 2px 8px rgba(64,158,255,0.1); }
.card-icon { font-size: 28px; display: block; margin-bottom: 6px; }
.card-title { font-weight: 600; font-size: 14px; }
.card-desc { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }

/* ── 消息列表 ─────────────────────────── */
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 0 16px;
}
.message {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}
.message.user { flex-direction: row-reverse; }
.message .avatar {
  width: 36px; height: 36px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; flex-shrink: 0;
  background: #f0f0f0;
}
.message .content {
  max-width: 78%;
  padding: 12px 16px;
  border-radius: 12px;
  line-height: 1.65;
  font-size: 14px;
  word-break: break-word;
}
.message.assistant .content { background: #fff; border: 1px solid #eee; }
.message.user .content { background: #409EFF; color: #fff; }

.dot-pulse::after {
  content: '';
  animation: dotPulse 1.5s infinite;
}
@keyframes dotPulse {
  0%   { content: ''; }
  25%  { content: '.'; }
  50%  { content: '..'; }
  75%  { content: '...'; }
  100% { content: ''; }
}

/* ── 审批卡片 ─────────────────────────── */
.approval-card {
  margin-top: 10px;
  padding: 14px;
  background: #FFF8E1;
  border: 1px solid #FFE082;
  border-radius: 8px;
  font-size: 13px;
}
.approval-title { margin-bottom: 8px; }
.approval-row { margin: 4px 0; }
.approval-row .label { color: #666; }
.sql-box {
  background: #fff; padding: 10px; border-radius: 6px;
  margin: 8px 0; font-size: 12px; overflow-x: auto;
}
.warn-box {
  background: #FFF3CD; color: #856404;
  padding: 8px 10px; border-radius: 6px; font-size: 12px; margin: 6px 0;
}
.btn-group { display: flex; gap: 8px; margin-top: 10px; }

/* ── 输入区 ───────────────────────────── */
.input-area {
  flex-shrink: 0;
  padding: 12px 0 20px;
  background: var(--bg-color);
}
.input-wrapper {
  display: flex;
  gap: 8px;
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 6px;
}
.chat-input {
  flex: 1;
  border: none;
  outline: none;
  padding: 10px 12px;
  font-size: 15px;
  background: transparent;
}
.chat-input:disabled { opacity: 0.5; }
.send-btn { height: 40px; min-width: 72px; }
.input-tip { font-size: 12px; color: #bbb; text-align: center; margin-top: 6px; }
</style>
