import { memo } from 'react'

interface StreamingTextProps {
  content: string
  isStreaming?: boolean
}

export const StreamingText = memo(function StreamingText({ content, isStreaming = true }: StreamingTextProps) {
  return (
    <div className="chat-text text-foreground break-words prose dark:prose-invert max-w-none prose-p:my-3 prose-li:my-1 prose-headings:mt-5 prose-headings:mb-2">
      <p className="whitespace-pre-wrap">
        {content}
        {isStreaming && (
          <span
            className="inline-block w-0.5 h-4 bg-foreground ml-0.5 align-middle animate-[cursor-blink_1s_steps(2)_infinite]"
            aria-hidden="true"
          />
        )}
      </p>
    </div>
  )
})

StreamingText.displayName = 'StreamingText'
