/**
 * 日期 / 文本格式化工具函数
 */

/** 格式化 ISO8601 自动停止时间为可读字符串 */
export function formatAutoStopTime(value?: string | null): string {
  if (!value) return '未设置'
  const date = parseServerDate(value)
  if (isNaN(date.getTime())) return String(value)
  const yyyy = date.getFullYear()
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  const hh = String(date.getHours()).padStart(2, '0')
  const mi = String(date.getMinutes()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`
}

/** 计算距自动停止时间的剩余文字描述 */
export function autoStopCountdown(value?: string | null, now = Date.now()): string {
  if (!value) return ''
  const target = parseServerDate(value).getTime()
  if (isNaN(target)) return ''
  const diff = target - now
  if (diff <= 0) return '即将停止'
  const totalMinutes = Math.ceil(diff / 60000)
  const days = Math.floor(totalMinutes / (24 * 60))
  const hours = Math.floor((totalMinutes % (24 * 60)) / 60)
  const minutes = totalMinutes % 60
  if (days > 0) return `${days}天${hours}小时${minutes}分钟`
  if (hours > 0) return `${hours}小时${minutes}分钟`
  return `${Math.max(minutes, 1)}分钟`
}

/** HTML 转义 */
export function escHtml(value: unknown): string {
  const div = document.createElement('div')
  div.appendChild(document.createTextNode(String(value ?? '')))
  return div.innerHTML
}

/**
 * 后端当前返回的 datetime 可能是不带时区的 UTC 字符串。
 * 若缺失时区后缀，则按 UTC 解释，避免浏览器按本地时区误解析。
 */
function parseServerDate(value: string): Date {
  const hasTimezone = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value)
  return new Date(hasTimezone ? value : `${value}Z`)
}
