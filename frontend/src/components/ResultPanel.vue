<script setup lang="ts">
/** 右侧结果面板（FE-8）：六段结构化渲染 + 复制 / 导出 Markdown */
import { computed } from 'vue'

import { useResultStore } from '@/stores/result'
import { renderMarkdown } from '@/utils/markdown'

defineProps<{
  /** 窄屏抽屉模式下展示关闭按钮 */
  drawerMode?: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

const resultStore = useResultStore()

const CONFIDENCE_META: Record<string, { text: string; cls: string }> = {
  high: { text: '高', cls: 'high' },
  medium: { text: '中', cls: 'medium' },
  low: { text: '低', cls: 'low' },
}

const conclusionHtml = computed(() => renderMarkdown(resultStore.result?.conclusion_text))
const missingHtml = computed(() => renderMarkdown(resultStore.result?.missing_data_text))
const nextActionHtml = computed(() => renderMarkdown(resultStore.result?.next_action_text))
</script>

<template>
  <div class="result-panel">
    <div class="panel-header">
      <button class="btn-ghost" :disabled="!resultStore.result" @click="resultStore.copy()">
        <svg viewBox="0 0 14 14" width="13" height="13" fill="none" aria-hidden="true">
          <rect x="4.5" y="4.5" width="8" height="8" rx="1.5" stroke="currentColor" stroke-width="1.2" />
          <path d="M9.5 4.5v-2a1.5 1.5 0 00-1.5-1.5H3A1.5 1.5 0 001.5 2.5v5A1.5 1.5 0 003 9h1.5" stroke="currentColor" stroke-width="1.2" />
        </svg>
        {{ resultStore.copied ? '已复制' : '复制' }}
      </button>
      <button
        class="btn-ghost"
        :disabled="!resultStore.result || resultStore.exporting"
        @click="resultStore.exportMarkdown()"
      >
        <svg viewBox="0 0 14 14" width="13" height="13" fill="none" aria-hidden="true">
          <path d="M7 9V1.5M4.5 6.5L7 9l2.5-2.5M2 10.5V12a1 1 0 001 1h8a1 1 0 001-1v-1.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        导出 Markdown
      </button>
      <button v-if="drawerMode" class="btn-ghost close-panel" title="收起" @click="emit('close')">×</button>
    </div>

    <div class="panel-body">
      <div v-if="resultStore.loading" class="panel-placeholder">
        <span class="spinner"></span>
        <p>报告加载中…</p>
      </div>

      <div v-else-if="resultStore.error" class="panel-placeholder">
        <p class="error-text">{{ resultStore.error }}</p>
      </div>

      <div v-else-if="!resultStore.result" class="panel-placeholder empty">
        <svg viewBox="0 0 48 48" width="44" height="44" fill="none" aria-hidden="true">
          <rect x="8" y="6" width="32" height="36" rx="4" stroke="#cbd2e0" stroke-width="2" />
          <path d="M15 33l5-7 4 3 8-11" stroke="#cbd2e0" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
          <path d="M28 18h4v4" stroke="#cbd2e0" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        <p>完成一轮分析后，<br />这里将展示六段结构化归因报告</p>
      </div>

      <template v-else>
        <section class="r-section">
          <h4 class="r-title">问题定义</h4>
          <p class="r-text">{{ resultStore.result.problem_definition }}</p>
        </section>

        <section class="r-section">
          <h4 class="r-title">关键指标</h4>
          <table class="r-table">
            <thead>
              <tr><th>指标名</th><th>数值</th><th>单位</th><th>口径</th></tr>
            </thead>
            <tbody>
              <tr v-for="(m, i) in resultStore.result.key_metrics" :key="i">
                <td>{{ m.metric_name }}</td>
                <td class="metric-value">{{ m.metric_value }}</td>
                <td>{{ m.metric_unit }}</td>
                <td>{{ m.metric_period }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="r-section">
          <h4 class="r-title">证据列表</h4>
          <div v-for="(e, i) in resultStore.result.evidence_list" :key="i" class="evidence">
            <div class="evidence-head">
              <span class="evidence-name">{{ e.source_name }}</span>
              <span class="conf" :class="CONFIDENCE_META[e.confidence]?.cls ?? 'low'">
                <span class="conf-dot"></span>{{ CONFIDENCE_META[e.confidence]?.text ?? e.confidence }}
              </span>
            </div>
            <p class="evidence-text">{{ e.evidence_text }}</p>
            <p class="evidence-metric">关联指标：{{ e.related_metric }}</p>
          </div>
        </section>

        <section class="r-section">
          <h4 class="r-title">归因结论</h4>
          <div class="conclusion md-body" v-html="conclusionHtml"></div>
        </section>

        <section class="r-section">
          <h4 class="r-title">待补充数据</h4>
          <div class="r-text md-body" v-html="missingHtml"></div>
        </section>

        <section class="r-section">
          <h4 class="r-title">下一步建议</h4>
          <div class="r-text md-body" v-html="nextActionHtml"></div>
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
.result-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--color-card);
}

.panel-header {
  flex-shrink: 0;
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 12px 14px;
  border-bottom: 1px solid var(--color-border);
}

.panel-header .btn-ghost {
  font-size: 12.5px;
}

.close-panel {
  margin-left: auto;
  font-size: 16px;
  padding: 6px 10px;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 14px 24px;
}

.panel-placeholder {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  color: var(--color-text-muted);
  font-size: 13px;
  text-align: center;
  line-height: 1.8;
}

.error-text {
  color: var(--color-danger);
}

.r-section {
  margin-bottom: 20px;
}

.r-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: 8px;
  padding-left: 8px;
  border-left: 3px solid var(--color-primary);
  line-height: 1.3;
}

.r-text {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.r-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.r-table th,
.r-table td {
  border: 1px solid var(--color-border);
  padding: 6px 8px;
  text-align: left;
}

.r-table th {
  background: #f7f9fd;
  font-weight: 500;
  color: var(--color-text-secondary);
  font-size: 12px;
}

.metric-value {
  font-weight: 600;
  color: var(--color-primary);
}

.evidence {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 9px 11px;
  margin-bottom: 8px;
}

.evidence-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.evidence-name {
  font-size: 13px;
  font-weight: 500;
}

.conf {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  flex-shrink: 0;
}

.conf-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.conf.high {
  color: var(--color-success);
}

.conf.high .conf-dot {
  background: var(--color-success);
}

.conf.medium {
  color: var(--color-warning);
}

.conf.medium .conf-dot {
  background: var(--color-warning);
}

.conf.low {
  color: var(--color-danger);
}

.conf.low .conf-dot {
  background: var(--color-danger);
}

.evidence-text {
  margin-top: 5px;
  font-size: 12.5px;
  color: var(--color-text-secondary);
}

.evidence-metric {
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--color-text-muted);
}

.conclusion {
  background: var(--color-success-light);
  border: 1px solid #a7f3d0;
  border-radius: var(--radius-md);
  padding: 10px 12px;
  font-size: 13px;
  color: #065f46;
}
</style>
