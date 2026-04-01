import { memo } from 'react'

interface StreamingTextProps {
  content: string
}

export const StreamingText = memo(function StreamingText({ content }: StreamingTextProps) {
  return (
    <div className="chat-text text-foreground break-words prose dark:prose-invert max-w-none prose-p:my-3 prose-li:my-1 prose-headings:mt-5 prose-headings:mb-2">
      <p className="whitespace-pre-wrap">{content}</p>
    </div>
  )
})

StreamingText.displayName = 'StreamingText'
