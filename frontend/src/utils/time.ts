/** 时间显示工具：契约时间为 ISO 8601 毫秒本地时间（无时区后缀），Date 直接按本地解析 */

function pad(n: number, w = 2): string {
  return String(n).padStart(w, '0')
}

/** 绝对时间：YYYY-MM-DD HH:mm:ss，withMs 时带毫秒 */
export function formatDateTime(iso: string | null | undefined, withMs = false): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const base = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  return withMs ? `${base}.${pad(d.getMilliseconds(), 3)}` : base
}

/** 相对时间：刚刚 / n分钟前 / n小时前 / 昨天 / n天前 / 日期 */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const diff = Date.now() - d.getTime()
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}小时前`
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const startOfThat = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const days = Math.round((startOfToday - startOfThat) / 86_400_000)
  if (days === 1) return '昨天'
  if (days > 1 && days <= 30) return `${days}天前`
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
