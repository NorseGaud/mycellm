import { useMemo } from 'react'
import { marked } from 'marked'
import type { Tokens } from 'marked'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'
import 'highlight.js/styles/github-dark-dimmed.css'
import { cn } from '@/lib/utils'

interface MarkdownRendererProps {
  content: string
  className?: string
}

function escapeHtmlForMarkdown(rawText: string): string {
  return rawText
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

// Configure marked with highlight.js
marked.setOptions({
  gfm: true,
  breaks: true,
})

const renderer = new marked.Renderer()
renderer.code = function ({ text, lang }: Tokens.Code) {
  if (lang && hljs.getLanguage(lang)) {
    const highlighted = hljs.highlight(text, { language: lang }).value
    return `<pre><code class="hljs language-${lang}">${highlighted}</code></pre>`
  }
  return `<pre><code class="hljs">${escapeHtmlForMarkdown(text)}</code></pre>`
}

// Raw HTML in markdown is shown as text, not parsed into the DOM
renderer.html = function ({ text }: Tokens.HTML | Tokens.Tag) {
  return escapeHtmlForMarkdown(text)
}

export function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  const sanitizedHtml = useMemo(() => {
    const parsedHtml = marked.parse(content, { renderer }) as string
    return DOMPurify.sanitize(parsedHtml)
  }, [content])

  return (
    <div
      className={cn('chat-md', className)}
      dangerouslySetInnerHTML={{ __html: sanitizedHtml }}
    />
  )
}
