# Gemini Voice & Message Actions Handoff

## Overview

7 frontend tasks for voice mode Phase A. All backend endpoints are already implemented and tested.

**Spec:** `docs/superpowers/specs/2026-03-26-voice-mode-design.md`

## API Endpoints Available

### POST /api/conversations/{conversation_id}/report
- **Auth:** Bearer token or session cookie (required)
- **Body:** `{ "message_index": int, "reason": "wrong"|"unhelpful"|"harmful", "message_content": string }`
- **Response:** `{ "status": "reported", "evaluation_id": string }`

### GET /api/audio/speak?text={text}
- **Auth:** Bearer token or session cookie (required)
- **Returns:** `audio/mpeg` stream
- **Returns 404** if `voice.tts_provider === "disabled"` in settings

### GET /api/settings
Returns (among other fields):
```json
{
  "voice": {
    "stt_provider": "groq",
    "tts_provider": "edge",
    "tts_voice": "en-US-AriaNeural",
    "groq_model": "whisper-large-v3-turbo"
  },
  "agent": {
    "name": "Odigos",
    "concise_mode": false,
    ...
  }
}
```

### POST /api/settings
Body example: `{ "agent": { "concise_mode": true } }`

### WebSocket /api/ws — New Message Types

**Client sends:**
- `{"type": "cancel"}` — stops generation. Server responds with `{"type": "stream_end", "cancelled": true, "conversation_id": "..."}`
- `{"type": "edit", "message_index": N, "content": "new text", "conversation_id": "..."}` — truncates history from index N and re-sends edited text as new message
- `{"type": "retry", "content": "original user message", "conversation_id": "..."}` — re-generates response for the given content

---

## Tasks

### G-V1: MessageActions Component

**Create:** `dashboard/src/components/MessageActions.tsx`

A horizontal icon bar that appears on hover below messages.

**Assistant message actions:**

| Action | Icon | Behavior |
|--------|------|----------|
| Copy | `Copy` | `navigator.clipboard.writeText(content)`, toast "Copied to clipboard" |
| Speak | `Volume2` | Calls `playTTS(stripForTTS(content))` — import `stripForTTS` from `@/lib/tts-filter` |
| Report | `Flag` | Opens small inline dropdown: Wrong / Unhelpful / Harmful. On select, POST to `/api/conversations/{conversationId}/report` |
| Retry | `RotateCcw` | Sends `{"type": "retry", "content": previousUserMessage}` over WebSocket. **Disabled while streaming.** |

**User message actions:**

| Action | Icon | Behavior |
|--------|------|----------|
| Copy | `Copy` | Same as above |
| Edit | `Pencil` | Makes message editable inline. On confirm (Enter or check button), sends `{"type": "edit", "message_index": N, "content": editedText}` over WebSocket |

**Styling:**
- Container: `opacity-0 group-hover/msg:opacity-100 transition-opacity flex items-center gap-2 mt-1`
- Icons: `h-4 w-4 text-muted-foreground hover:text-foreground cursor-pointer`
- Position: below message content, left-aligned

**Props:**
```typescript
interface MessageActionsProps {
  role: 'user' | 'assistant'
  content: string
  messageIndex: number
  conversationId: string
  previousUserMessage?: string  // for retry (assistant messages only)
  isStreaming: boolean          // disable retry while streaming
  ttsAvailable: boolean        // hide speak if TTS disabled
  socket: ChatSocket | null    // ChatSocket from '@/lib/ws' (socketRef.current)
  onEdit: (index: number, content: string) => void
  playTTS: (text: string) => void
}
```

**Report dropdown:** Small absolute-positioned div below the Flag icon with three options. Each option sends the POST request with the appropriate reason. Show a toast on success ("Report submitted"). Close dropdown on selection or click-outside.

---

### G-V2: TTS Filter Utility

**Create:** `dashboard/src/lib/tts-filter.ts`

```typescript
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
```

---

### G-V3: Stop Button

**Modify:** `dashboard/src/components/ChatPanel.tsx`

Replace the Send button with a contextual Send/Stop button:

**State tracking:**
```typescript
const [isStreaming, setIsStreaming] = useState(false)
```

Set `isStreaming = true` when a chat message is sent (in the send handler).
Set `isStreaming = false` when receiving `chat_response` or `stream_end` message types from WebSocket.

**Button rendering (replace existing send button):**
```tsx
{isStreaming ? (
  <Button
    size="icon"
    aria-label="Stop generation"
    className="h-8 w-8 rounded-lg bg-red-500 hover:bg-red-600 text-white"
    onClick={() => {
      socketRef.current?.send(JSON.stringify({ type: 'cancel' }))
      setIsStreaming(false)
    }}
  >
    <Square className="h-4 w-4" />
  </Button>
) : (
  <Button
    size="icon"
    aria-label="Send message"
    className="h-8 w-8 rounded-lg"
    disabled={!inputValue.trim() || !connected}
    onClick={handleSend}
  >
    <ArrowUp className="h-4 w-4" />
  </Button>
)}
```

**WebSocket message handling:** In the WebSocket `onmessage` handler, add:
```typescript
case 'stream_end':
  setIsStreaming(false)
  break
```

---

### G-V4: Auto-Read Toggle

**Modify:** `dashboard/src/components/ChatPanel.tsx`

**State:**
```typescript
const [autoRead, setAutoRead] = useState(() =>
  localStorage.getItem('odigos-auto-read') === 'true'
)
const currentAudioRef = useRef<HTMLAudioElement | null>(null)
```

**Toggle button** — render in the chat header area (near conversation title):
```tsx
{ttsAvailable && (
  <button
    onClick={() => {
      const next = !autoRead
      setAutoRead(next)
      localStorage.setItem('odigos-auto-read', String(next))
    }}
    className={`p-1 rounded ${autoRead ? 'text-primary' : 'text-muted-foreground'} hover:text-foreground`}
    title="Auto-read responses"
  >
    <Volume2 className="h-4 w-4" />
    {autoRead && <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-primary rounded-full" />}
  </button>
)}
```

**Auto-read trigger:** After receiving a `chat_response` (and NOT `stream_end.cancelled`), if `autoRead` is true:
```typescript
if (autoRead && ttsAvailable && shouldPlayTTS(responseContent)) {
  playTTS(stripForTTS(responseContent))
}
```

**Audio management in playTTS:**
```typescript
const playTTS = useCallback(async (text: string) => {
  // Stop any currently playing audio
  if (currentAudioRef.current) {
    currentAudioRef.current.pause()
    currentAudioRef.current.src = ''
    currentAudioRef.current = null
  }

  if (!text) return

  try {
    const res = await fetch(`/api/audio/speak?text=${encodeURIComponent(text)}`, {
      credentials: 'include',  // send session cookie
    })
    if (!res.ok) return
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const audio = new Audio(url)
    currentAudioRef.current = audio
    audio.onended = () => {
      URL.revokeObjectURL(url)
      currentAudioRef.current = null
    }
    audio.play()
  } catch {
    // silent fail
  }
}, [])
```

**Stop button integration:** When the stop button is clicked, also stop audio:
```typescript
if (currentAudioRef.current) {
  currentAudioRef.current.pause()
  currentAudioRef.current = null
}
```

---

### G-V5: Fix Voice Detection

**Modify:** `dashboard/src/components/ChatPanel.tsx`

**Replace single state with two:**
```typescript
// OLD:
const [voiceEnabled, setVoiceEnabled] = useState(false)

// NEW:
const [sttAvailable, setSttAvailable] = useState(false)
const [ttsAvailable, setTtsAvailable] = useState(false)
```

**Fix the settings check (line ~251):**
```typescript
// OLD:
.then((s) => setVoiceEnabled(!!(s.stt?.enabled || s.tts?.enabled)))

// NEW:
.then((s) => {
  setSttAvailable(s.voice?.stt_provider !== 'disabled')
  setTtsAvailable(s.voice?.tts_provider !== 'disabled')
})
```

**Update all references:**
- Mic button: `{sttAvailable && (<Button ...>` (was `voiceEnabled`)
- Speak on messages / auto-read: check `ttsAvailable`
- Pass `ttsAvailable` as prop to `MessageActions`

---

### G-V6: Concise Mode Toggle

**Modify:** `dashboard/src/components/ChatPanel.tsx`

**State:**
```typescript
const [conciseMode, setConciseMode] = useState(false)
```

**Load from settings on mount** (in the same useEffect that loads voice settings):
```typescript
.then((s) => {
  setSttAvailable(s.voice?.stt_provider !== 'disabled')
  setTtsAvailable(s.voice?.tts_provider !== 'disabled')
  setConciseMode(s.agent?.concise_mode ?? false)
})
```

**Toggle handler:**
```typescript
const toggleConciseMode = useCallback(async () => {
  const next = !conciseMode
  setConciseMode(next)
  try {
    await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ agent: { concise_mode: next } }),
    })
  } catch {
    setConciseMode(!next)  // revert on failure
  }
}, [conciseMode])
```

**Toggle button** — render in chat header next to auto-read:
```tsx
<button
  onClick={toggleConciseMode}
  className={`p-1 rounded ${conciseMode ? 'text-primary' : 'text-muted-foreground'} hover:text-foreground`}
  title="Concise mode"
>
  <AlignLeft className="h-4 w-4" />
</button>
```

---

### G-V7: ChatPanel Integration

**Modify:** `dashboard/src/components/ChatPanel.tsx`

Wire everything together:

**1. New imports:**
```typescript
import { Copy, Flag, RotateCcw, Pencil, Square, AlignLeft, Volume2 } from 'lucide-react'
import { MessageActions } from '@/components/MessageActions'
import { stripForTTS, shouldPlayTTS } from '@/lib/tts-filter'
```

**2. Replace existing message rendering** (both user and assistant messages) to include `MessageActions`:

For assistant messages (replace the existing `group/msg` block with single speaker button):
```tsx
<div className="group/msg w-full overflow-hidden">
  <div className="chat-text text-foreground break-words prose dark:prose-invert max-w-none prose-p:my-3 prose-li:my-1 prose-headings:mt-5 prose-headings:mb-2">
    <Markdown>{msg.content}</Markdown>
  </div>
  <MessageActions
    role="assistant"
    content={msg.content}
    messageIndex={actualMessageIndex}
    conversationId={activeConversationId || ''}
    previousUserMessage={getPreviousUserMessage(actualMessageIndex)}
    isStreaming={isStreaming}
    ttsAvailable={ttsAvailable}
    socket={socketRef.current}
    onEdit={() => {}}
    playTTS={(text) => playTTS(stripForTTS(text))}
  />
</div>
```

For user messages (add actions to the existing user bubble):
```tsx
<div className="group/msg flex justify-end">
  <div className="max-w-[85%]">
    <div className="rounded-3xl bg-muted/60 px-5 py-3">
      <div className="text-sm text-foreground whitespace-pre-wrap leading-relaxed break-words overflow-hidden">{msg.content}</div>
    </div>
    <MessageActions
      role="user"
      content={msg.content}
      messageIndex={actualMessageIndex}
      conversationId={activeConversationId || ''}
      isStreaming={isStreaming}
      ttsAvailable={ttsAvailable}
      socket={socketRef.current}
      onEdit={handleEdit}
      playTTS={(text) => playTTS(stripForTTS(text))}
    />
  </div>
</div>
```

**3. Helper function for getting previous user message:**
```typescript
const getPreviousUserMessage = (assistantIndex: number): string => {
  // Walk backwards from this assistant message to find the preceding user message
  for (let i = assistantIndex - 1; i >= 0; i--) {
    if (messages[i]?.role === 'user') return messages[i].content
  }
  return ''
}
```

**4. Edit handler:**
```typescript
const handleEdit = useCallback((messageIndex: number, content: string) => {
  socketRef.current?.send(JSON.stringify({
    type: 'edit',
    message_index: messageIndex,
    content,
    conversation_id: activeConversationId,
  }))
  // Truncate local messages state to match
  setMessages(prev => prev.slice(0, messageIndex))
}, [activeConversationId])
```

**5. `actualMessageIndex` calculation:**
When rendering `messages.slice(-messageDisplayLimit)`, the actual index in the full array is:
```typescript
const offset = Math.max(0, messages.length - messageDisplayLimit)
// In the map: actualMessageIndex = offset + i
```

**6. Chat header toggles** — add auto-read and concise mode toggles near the top of the chat area (after the conversation title area).

## Icons to Import

Add to existing lucide-react imports in ChatPanel.tsx:
```typescript
import { Copy, Flag, RotateCcw, Pencil, Square, AlignLeft } from 'lucide-react'
```
Note: `Volume2`, `Mic`, `MicOff`, `ArrowUp`, `Paperclip`, `X`, `PanelRightClose`, `Download` are already imported.

## Testing Checklist

- [ ] Hover over assistant message: see Copy, Speak, Report, Retry icons
- [ ] Hover over user message: see Copy, Edit icons
- [ ] Copy: copies text, shows toast
- [ ] Speak: reads message aloud (no code, no URLs)
- [ ] Report: dropdown appears, selecting option shows "Report submitted" toast
- [ ] Retry: re-sends previous user message (disabled during streaming)
- [ ] Edit: message becomes editable, confirm re-sends
- [ ] Stop button: appears during streaming, stops generation
- [ ] Auto-read toggle: persists, reads new responses aloud
- [ ] Concise mode toggle: persists server-side, agent responds more briefly
- [ ] Mic button: only visible when `stt_provider !== "disabled"`
- [ ] Speak/auto-read: hidden when `tts_provider === "disabled"`
- [ ] TTS filter: code blocks, URLs, and inline code not read aloud
- [ ] No concurrent audio: starting new TTS stops previous
