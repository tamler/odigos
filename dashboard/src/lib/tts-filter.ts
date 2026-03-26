/**
 * Strip markdown formatting that sounds bad when read aloud.
 * Rules applied in order:
 * 1. Remove fenced code blocks (```...```)
 * 2. Remove indented code blocks (4+ spaces or tab at line start)
 * 3. Replace URLs (https?://...) with "link"
 * 4. Strip inline code backticks: `foo` -> foo
 * 5. Strip markdown images: ![alt](url) -> alt
 * 6. Strip markdown links: [text](url) -> text
 * 7. Strip HTML tags
 * 8. Collapse multiple newlines into single newline
 * 9. Trim whitespace
 */
export function stripForTTS(text: string): string {
  let result = text

  // 1. Remove fenced code blocks
  result = result.replace(/```[\s\S]*?```/g, '')

  // 2. Remove indented code blocks (lines starting with 4+ spaces or tab)
  result = result.replace(/^(?:    |\t).*$/gm, '')

  // 3. Replace URLs
  result = result.replace(/https?:\/\/\S+/g, 'link')

  // 4. Strip inline code
  result = result.replace(/`([^`]+)`/g, '$1')

  // 5. Strip images
  result = result.replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')

  // 6. Strip links (keep text)
  result = result.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')

  // 7. Strip HTML tags
  result = result.replace(/<[^>]+>/g, '')

  // 8. Collapse multiple newlines
  result = result.replace(/\n{2,}/g, '\n')

  // 9. Trim
  result = result.trim()

  // Truncate long messages at sentence boundary
  if (result.length > 2000) {
    const truncated = result.slice(0, 2000)
    const lastSentence = truncated.search(/[.!?]\s[^.!?]*$/)
    if (lastSentence > 0) {
      result = truncated.slice(0, lastSentence + 1) + ' ... and more'
    } else {
      result = truncated + '... and more'
    }
  }

  return result
}

/**
 * Returns true if the text has speakable content after filtering.
 */
export function shouldPlayTTS(text: string): boolean {
  return stripForTTS(text).length > 0
}
