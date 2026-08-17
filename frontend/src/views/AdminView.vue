<script setup lang="ts">
/** 管理页（FE-10 / CFG）：配置分组查看 + 热更新；任务日志查看器 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAdminStore } from '@/stores/admin'
import { STEP_TEXT, TASK_STATUS_META } from '@/stores/task'
import { formatDateTime } from '@/utils/time'

const router = useRouter()
const adminStore = useAdminStore()

const activeTab = ref<'configs' | 'logs'>('configs')
const taskIdInput = ref('')

const GROUP_META: Record<string, string> = {
  llm: 'LLM 模型',
  agent: 'Agent 参数',
  datasource: '数据源',
  feature: '功能开关',
}

const groupedConfigs = computed(() => {
  const groups: Array<{ group: string; label: string; items: typeof adminStore.configs }> = []
  for (const key of Object.keys(GROUP_META)) {
    const items = adminStore.configs.filter((c) => c.config_group === key)
    if (items.length) groups.push({ group: key, label: GROUP_META[key]!, items })
  }
  // 未知分组兜底展示
  const known = Object.keys(GROUP_META)
  const others = adminStore.configs.filter((c) => !known.includes(c.config_group))
  if (others.length) groups.push({ group: 'other', label: '其他', items: others })
  return groups
})

function queryTask(): void {
  const id = Number(taskIdInput.value.trim())
  if (!Number.isInteger(id) || id <= 0) return
  void adminStore.queryTask(id)
}

function levelCls(level: string): string {
  if (level === 'error') return 'error'
  if (level === 'warn') return 'warn'
  return 'info'
}

onMounted(() => {
  void adminStore.loadConfigs()
})
</script>

<template>
  <div class="admin-page">
    <header class="admin-header">
      <button class="back-btn" @click="router.push('/workbench')">
        <svg viewBox="0 0 16 16" width="14" height="14" fill="none" aria-hidden="true">
          <path d="M10 3L5 8l5 5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        返回工作台
      </button>
      <h1 class="admin-title">系统管理</h1>
      <div class="tabs">
        <button class="tab" :class="{ active: activeTab === 'configs' }" @click="activeTab = 'configs'">配置管理</button>
        <button class="tab" :class="{ active: activeTab === 'logs' }" @click="activeTab = 'logs'">任务日志</button>
      </div>
    </header>

    <div class="admin-body">
      <!-- 配置管理 -->
      <div v-if="activeTab === 'configs'" class="tab-panel">
        <div class="panel-toolbar">
          <p class="toolbar-hint">配置为只读展示，修改请直接更新数据库 system_configs 表后重载</p>
          <button class="btn-primary" :disabled="adminStore.reloading" @click="adminStore.reload()">
            <span v-if="adminStore.reloading" class="spinner"></span>
            {{ adminStore.reloading ? '重载中…' : '重载配置' }}
          </button>
        </div>

        <div
          v-if="adminStore.reloadResult"
          class="reload-result"
          :class="adminStore.reloadResult.status === 'ok' ? 'ok' : 'error'"
        >
          {{ adminStore.reloadResult.status === 'ok' ? '重载成功' : '重载失败' }}：{{ adminStore.reloadResult.message }}
        </div>

        <div v-if="adminStore.configsLoading" class="panel-state"><span class="spinner"></span></div>

        <div v-else-if="adminStore.configsUnavailable" class="panel-state placeholder">
          <p>后端暂未提供配置读取接口（GET /api/admin/configs）。</p>
          <p class="sub">该接口为前端约定的配套接口，待后端补充后即可展示；当前仍可使用「重载配置」。</p>
        </div>

        <div v-else-if="adminStore.configsError" class="panel-state placeholder">
          <p class="error-text">{{ adminStore.configsError }}</p>
        </div>

        <div v-else class="config-groups">
          <section v-for="g in groupedConfigs" :key="g.group" class="config-group">
            <h3 class="group-title">{{ g.label }}</h3>
            <table class="config-table">
              <thead>
                <tr><th>配置键</th><th>当前值</th><th>说明</th><th>更新时间</th></tr>
              </thead>
              <tbody>
                <tr v-for="c in g.items" :key="c.config_key">
                  <td class="cfg-key">{{ c.config_key }}</td>
                  <td class="cfg-value">{{ c.config_value }}</td>
                  <td class="cfg-desc">{{ c.description }}</td>
                  <td class="cfg-time">{{ formatDateTime(c.updated_at) }}</td>
                </tr>
              </tbody>
            </table>
          </section>
        </div>
      </div>

      <!-- 任务日志 -->
      <div v-else class="tab-panel">
        <div class="panel-toolbar">
          <div class="task-query">
            <input
              v-model="taskIdInput"
              class="task-input"
              placeholder="输入任务 ID，如 301"
              @keydown.enter.prevent="queryTask"
            />
            <button class="btn-primary" :disabled="adminStore.taskLoading" @click="queryTask">查询</button>
          </div>
        </div>

        <div v-if="adminStore.taskLoading" class="panel-state"><span class="spinner"></span></div>

        <div v-else-if="adminStore.taskError" class="panel-state placeholder">
          <p class="error-text">{{ adminStore.taskError }}</p>
        </div>

        <div v-else-if="adminStore.taskInfo" class="task-result">
          <div class="task-card">
            <span
              class="task-badge"
              :style="{
                color: TASK_STATUS_META[adminStore.taskInfo.task_status].color,
                background: `${TASK_STATUS_META[adminStore.taskInfo.task_status].color}1a`,
              }"
            >
              {{ TASK_STATUS_META[adminStore.taskInfo.task_status].text }}
            </span>
            <div class="task-fields">
              <div class="field"><label>任务 ID</label><span>{{ adminStore.taskInfo.task_id }}</span></div>
              <div class="field">
                <label>当前阶段</label>
                <span>{{ adminStore.taskInfo.current_step ? STEP_TEXT[adminStore.taskInfo.current_step] : '—' }}</span>
              </div>
              <div class="field"><label>开始时间</label><span>{{ formatDateTime(adminStore.taskInfo.started_at) }}</span></div>
              <div class="field"><label>结束时间</label><span>{{ formatDateTime(adminStore.taskInfo.finished_at) }}</span></div>
            </div>
            <p v-if="adminStore.taskInfo.error_message" class="task-error">{{ adminStore.taskInfo.error_message }}</p>
          </div>

          <table v-if="adminStore.taskLogs.length" class="log-table">
            <thead>
              <tr><th>时间</th><th>级别</th><th>类型</th><th>内容</th></tr>
            </thead>
            <tbody>
              <tr v-for="(log, i) in adminStore.taskLogs" :key="i">
                <td class="log-time">{{ formatDateTime(log.created_at, true) }}</td>
                <td><span class="log-level" :class="levelCls(log.log_level)">{{ log.log_level }}</span></td>
                <td class="log-type">{{ log.log_type }}</td>
                <td class="log-content" :class="{ error: log.log_level === 'error' }">{{ log.log_content }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="panel-state placeholder"><p>该任务暂无日志</p></div>
        </div>

        <div v-else class="panel-state placeholder">
          <p>输入任务 ID 查看运行状态与执行日志</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.admin-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--color-bg);
}

.admin-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 13px 24px;
  background: var(--color-card);
  border-bottom: 1px solid var(--color-border);
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.back-btn:hover {
  color: var(--color-primary);
}

.admin-title {
  font-size: 16px;
  font-weight: 600;
}

.tabs {
  display: flex;
  gap: 4px;
  margin-left: 12px;
}

.tab {
  padding: 6px 14px;
  border-radius: var(--radius-md);
  font-size: 13.5px;
  color: var(--color-text-secondary);
  transition: all 0.12s ease;
}

.tab:hover {
  background: var(--color-bg);
}

.tab.active {
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-weight: 500;
}

.admin-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px 32px;
}

.tab-panel {
  max-width: 980px;
  margin: 0 auto;
}

.panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.toolbar-hint {
  font-size: 12.5px;
  color: var(--color-text-muted);
}

.reload-result {
  border-radius: var(--radius-md);
  padding: 10px 14px;
  font-size: 13px;
  margin-bottom: 14px;
}

.reload-result.ok {
  background: var(--color-success-light);
  border: 1px solid #a7f3d0;
  color: #047857;
}

.reload-result.error {
  background: var(--color-danger-light);
  border: 1px solid #fecaca;
  color: #b91c1c;
}

.panel-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 0;
  gap: 10px;
}

.panel-state.placeholder {
  color: var(--color-text-secondary);
  font-size: 13.5px;
  text-align: center;
}

.panel-state .sub {
  font-size: 12.5px;
  color: var(--color-text-muted);
}

.error-text {
  color: var(--color-danger);
}

.config-groups {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.config-group {
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.group-title {
  font-size: 14px;
  font-weight: 600;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border);
  background: #f8fafd;
}

.config-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.config-table th,
.config-table td {
  padding: 9px 16px;
  text-align: left;
  border-bottom: 1px solid var(--color-border);
}

.config-table tr:last-child td {
  border-bottom: none;
}

.config-table th {
  font-size: 12px;
  color: var(--color-text-muted);
  font-weight: 500;
}

.cfg-key {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--color-primary);
  white-space: nowrap;
}

.cfg-value {
  font-family: var(--font-mono);
  font-size: 12.5px;
  word-break: break-all;
}

.cfg-desc {
  color: var(--color-text-secondary);
}

.cfg-time {
  color: var(--color-text-muted);
  font-size: 12px;
  white-space: nowrap;
}

.task-query {
  display: flex;
  gap: 10px;
  flex: 1;
}

.task-input {
  width: 260px;
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 8px 12px;
  font-size: 13.5px;
}

.task-input:focus {
  border-color: var(--color-primary-border);
}

.task-card {
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: 16px;
  margin-bottom: 16px;
}

.task-badge {
  display: inline-block;
  font-size: 12.5px;
  border-radius: 6px;
  padding: 2px 10px;
  font-weight: 500;
}

.task-fields {
  margin-top: 12px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 10px;
}

.field label {
  display: block;
  font-size: 11.5px;
  color: var(--color-text-muted);
  margin-bottom: 2px;
}

.field span {
  font-size: 13px;
}

.task-error {
  margin-top: 12px;
  background: var(--color-danger-light);
  border: 1px solid #fecaca;
  color: #b91c1c;
  border-radius: var(--radius-md);
  padding: 8px 12px;
  font-size: 12.5px;
}

.log-table {
  width: 100%;
  border-collapse: collapse;
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
  font-size: 12.5px;
}

.log-table th,
.log-table td {
  padding: 8px 14px;
  text-align: left;
  border-bottom: 1px solid var(--color-border);
}

.log-table th {
  background: #f8fafd;
  font-size: 12px;
  color: var(--color-text-muted);
  font-weight: 500;
}

.log-time {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--color-text-muted);
  white-space: nowrap;
}

.log-level {
  font-size: 11.5px;
  border-radius: 4px;
  padding: 1px 7px;
  font-weight: 500;
}

.log-level.info {
  background: #f1f5f9;
  color: #64748b;
}

.log-level.warn {
  background: var(--color-warning-light);
  color: #b45309;
}

.log-level.error {
  background: var(--color-danger-light);
  color: #b91c1c;
}

.log-type {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.log-content {
  color: var(--color-text-secondary);
  word-break: break-all;
}

.log-content.error {
  color: #b91c1c;
}
</style>
