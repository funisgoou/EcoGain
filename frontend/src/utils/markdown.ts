import DOMPurify from 'dompurify'
import { marked } from 'marked'

marked.setOptions({ breaks: true, gfm: true })

/** Markdown → 消毒后的 HTML（marked + DOMPurify，SPEC 指定组合） */
export function renderMarkdown(text: string | null | undefined): string {
  if (!text) return ''
  const html = marked.parse(text, { async: false })
  return DOMPurify.sanitize(html)
}
