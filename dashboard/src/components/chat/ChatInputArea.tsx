import { useNavigate } from 'react-router-dom'
import { ArrowUp, Paperclip, X, Mic, Square, Camera } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { FileUploadTrigger } from '@/components/ui/file-upload'
import { getFileIcon, formatFileSize } from '@/components/ArtifactCard'
import { useUIStore } from '@/stores/uiStore'
import type { ChatSocket } from '@/lib/ws'

interface PendingFile {
  file: File
  id?: string
  uploading?: boolean
  progress?: number
}

interface ChatInputAreaProps {
  inputValue: string
  setInputValue: (value: string) => void
  pendingFiles: PendingFile[]
  handleSend: () => void
  removeFile: (file: File) => void
  handleKeyDown: (e: React.KeyboardEvent) => void
  textareaRef: React.RefObject<HTMLTextAreaElement | null>
  connected: boolean
  canSend: boolean
  isStreaming: boolean
  sttAvailable: boolean
  setUseCamera: (value: boolean | 'environment') => void
  agentName: string
  isSidePanel: boolean
  hasNewEmail: boolean
  isMobile: boolean
  pushToTalk: {
    recording: boolean
    start: () => void
    stop: () => void
  }
  socketRef: React.MutableRefObject<ChatSocket | null>
  stopTTS: () => void
  onEmailClick: () => void
}

function BackgroundTaskIndicator() {
  const tasks = useUIStore(s => s.backgroundTasks)
  if (tasks.length === 0) return null

  return (
    <div className="flex items-center gap-2 text-[10px] text-muted-foreground bg-muted/30 px-2 py-0.5 rounded-full border border-border/30">
      <div className="h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse" />
      <span className="font-medium">
        {tasks.length === 1
          ? `${tasks[0].description}...`
          : `${tasks.length} tasks running...`
        }
      </span>
    </div>
  )
}

export function ChatInputArea({
  inputValue,
  setInputValue,
  pendingFiles,
  handleSend,
  removeFile,
  handleKeyDown,
  textareaRef,
  connected,
  canSend,
  isStreaming,
  sttAvailable,
  setUseCamera,
  agentName,
  isSidePanel,
  hasNewEmail,
  isMobile,
  pushToTalk,
  socketRef,
  stopTTS,
  onEmailClick,
}: ChatInputAreaProps) {
  const navigate = useNavigate()

  return (
    <div className="pb-safe pt-2 px-4 shrink-0 bg-background/50 backdrop-blur-sm">
      <div className={`w-full mx-auto ${!isSidePanel ? 'max-w-[52rem]' : ''} pb-4 sm:pb-4`}>
        {pendingFiles.length > 0 && (
          <div className="flex flex-wrap gap-2 pb-3">
            {pendingFiles.map((p, i) => (
              <div
                key={i}
                className="flex items-center gap-2.5 px-3 py-2 rounded-lg bg-muted border border-border/50 text-sm max-w-[240px] shadow-sm relative overflow-hidden group"
              >
                <div className="text-muted-foreground shrink-0 flex items-center justify-center p-1 bg-background rounded-md">
                  {getFileIcon(p.file.type || 'application/octet-stream', p.file.name)}
                </div>
                <div className="flex flex-col min-w-0 flex-1 py-0.5">
                  <span className="truncate text-xs font-semibold">{p.file.name}</span>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-[10px] text-muted-foreground">{formatFileSize(p.file.size)}</span>
                    {p.uploading && (
                      <div className="flex items-center gap-1.5 ml-auto">
                        <div className="h-1 flex-1 bg-background rounded-full overflow-hidden w-10">
                          <div className="h-full bg-primary transition-all duration-300" style={{ width: `${p.progress || 0}%` }} />
                        </div>
                        <span className="text-[9px] text-muted-foreground font-medium w-5 text-right">{p.progress || 0}%</span>
                      </div>
                    )}
                  </div>
                </div>
                {!p.uploading && (
                  <button onClick={() => removeFile(p.file)} aria-label="Remove file" className="shrink-0 text-muted-foreground hover:text-foreground p-1 rounded-sm hover:bg-background transition-colors absolute right-1.5 top-1.5 opacity-0 group-hover:opacity-100">
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="flex items-center justify-end px-1 mb-2">
          <BackgroundTaskIndicator />
        </div>

        <div className="relative rounded-2xl border border-border/50 bg-muted/30 focus-within:border-border/80 transition-colors shadow-sm">
          <textarea
            ref={textareaRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={`Message ${agentName}...`}
            disabled={!connected}
            rows={1}
            className="w-full resize-none bg-transparent px-4 pt-3 pb-14 sm:pb-12 text-base sm:text-sm text-foreground placeholder:text-muted-foreground focus:outline-none disabled:opacity-50 min-h-[52px]"
          />
          <div className="absolute bottom-2 left-2 right-2 flex items-center justify-between">
            <div className="flex items-center gap-1">
              <FileUploadTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Attach file"
                  className="h-11 w-11 lg:h-8 lg:w-8 rounded-lg text-muted-foreground hover:text-foreground"
                  disabled={!connected}
                  onClick={() => setUseCamera(false)}
                >
                  <Paperclip className="h-5 w-5 lg:h-4 lg:w-4" />
                </Button>
              </FileUploadTrigger>

              {isMobile && (
                <FileUploadTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="Take photo"
                    className="h-11 w-11 rounded-lg text-muted-foreground hover:text-foreground"
                    disabled={!connected}
                    onClick={() => setUseCamera('environment')}
                  >
                    <Camera className="h-5 w-5" />
                  </Button>
                </FileUploadTrigger>
              )}
            </div>

            <div className="flex items-center gap-1">
              {sttAvailable && (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={pushToTalk.recording ? "Tap to stop" : "Tap to speak"}
                  className={`h-11 w-11 lg:h-8 lg:w-8 rounded-lg transition-colors ${pushToTalk.recording ? 'bg-red-500 text-white animate-pulse' : 'text-muted-foreground hover:text-foreground'}`}
                  disabled={!connected}
                  onClick={() => {
                    stopTTS()
                    if (pushToTalk.recording) {
                      pushToTalk.stop()
                    } else {
                      pushToTalk.start()
                    }
                  }}
                >
                  {pushToTalk.recording ? <Square className="h-4 w-4 lg:h-3.5 lg:w-3.5" /> : <Mic className="h-5 w-5 lg:h-4 lg:w-4" />}
                </Button>
              )}
              {isStreaming ? (
                <Button
                  size="icon"
                  aria-label="Stop generation"
                  className="h-11 w-11 lg:h-8 lg:w-8 rounded-lg bg-red-500 hover:bg-red-600 text-white shadow-sm transition-all active:scale-95 flex items-center justify-center"
                  onClick={() => {
                    socketRef.current?.send('cancel')
                    stopTTS()
                  }}
                >
                  <Square className="h-5 w-5 lg:h-4 lg:w-4 fill-current" />
                </Button>
              ) : (
                <Button
                  size="icon"
                  aria-label="Send message"
                  className="h-11 w-11 lg:h-8 lg:w-8 rounded-lg shadow-sm transition-all active:scale-95 flex items-center justify-center"
                  disabled={!canSend}
                  onClick={() => handleSend()}
                >
                  <ArrowUp className="h-5 w-5 lg:h-4 lg:w-4" />
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
