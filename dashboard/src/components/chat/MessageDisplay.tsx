import { Markdown } from '@/components/ui/markdown'
import { StreamingText } from '@/components/ui/streaming-text'
import {
  ChatContainerRoot,
  ChatContainerContent,
  ChatContainerScrollAnchor,
} from '@/components/ui/chat-container'
import { Artifact } from '@/components/ArtifactCard'
import { MessageActions } from '@/components/MessageActions'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { WelcomeView } from '@/components/chat/WelcomeView'
import { ArtifactGallery } from '@/components/chat/ArtifactGallery'
import { VoiceModePanel } from '@/components/chat/VoiceModePanel'
import type { ChatMessage } from '@/layouts/AppLayout'
import type { ChatSocket } from '@/lib/ws'

interface MessageDisplayProps {
  messages: ChatMessage[]
  streamingContent: string
  thinking: boolean
  status: string | null
  artifacts: Artifact[]
  messageDisplayLimit: number
  switchingConversation: boolean
  voiceMode: {
    active: boolean
    phase: string
    exit: () => void
  }
  voiceAmplitude: number
  isStreaming: boolean
  ttsAvailable: boolean
  activeConversationId: string | null
  agentName: string
  isSidePanel: boolean
  socket: ChatSocket | null
  playTTS: (text: string) => void
  stopTTS: () => void
  isTTSPlaying: boolean
  onLoadMore: () => void
  onEdit: (messageIndex: number, content: string) => void
  onOpenArtifact: (id: string) => void
  onSuggest: (text: string) => void
  getPreviousUserMessage: (assistantIndex: number) => string
}

export function MessageDisplay({
  messages,
  streamingContent,
  thinking,
  status,
  artifacts,
  messageDisplayLimit,
  switchingConversation,
  voiceMode,
  voiceAmplitude,
  isStreaming,
  ttsAvailable,
  activeConversationId,
  agentName,
  isSidePanel,
  socket,
  playTTS,
  stopTTS,
  isTTSPlaying,
  onLoadMore,
  onEdit,
  onOpenArtifact,
  onSuggest,
  getPreviousUserMessage,
}: MessageDisplayProps) {
  return (
    <ChatContainerRoot className="flex-1 w-full relative z-0">
      <ChatContainerContent>
        <div className={`w-full h-full mx-auto px-4 py-6 ${!isSidePanel ? 'max-w-[52rem]' : ''}`}>
          {messages.length === 0 && !activeConversationId ? (
            <WelcomeView
              agentName={agentName}
              onSuggest={onSuggest}
            />
          ) : (
            <div className="flex-1 flex flex-col h-full min-h-0">
              {voiceMode.active ? (
                <VoiceModePanel
                  messages={messages}
                  amplitude={voiceAmplitude}
                  phase={voiceMode.phase}
                  onExit={() => voiceMode.exit()}
                />
              ) : switchingConversation ? (
                <div className="space-y-6 py-6">
                  <div className="flex justify-end gap-3">
                    <div className="space-y-2 max-w-[70%] w-full">
                      <Skeleton className="h-4 w-[80%] ml-auto" />
                      <Skeleton className="h-4 w-[55%] ml-auto" />
                    </div>
                  </div>
                  <div className="flex gap-3">
                    <div className="space-y-2 max-w-[75%] w-full">
                      <Skeleton className="h-4 w-[90%]" />
                      <Skeleton className="h-4 w-[65%]" />
                      <Skeleton className="h-4 w-[40%]" />
                    </div>
                  </div>
                </div>
              ) : (
                <div className="space-y-6 animate-in fade-in duration-300">
                  {messages.length === 0 && !thinking && (
                    <div className="flex items-center justify-center h-[60vh] text-muted-foreground text-base text-center">
                      What can I help you with?
                    </div>
                  )}

                  {messages.length > messageDisplayLimit && (
                    <div className="flex justify-center pb-2">
                      <Button variant="outline" size="sm" onClick={onLoadMore} className="text-xs h-7">
                        Load earlier messages
                      </Button>
                    </div>
                  )}

                  {(() => {
                    const offset = Math.max(0, messages.length - messageDisplayLimit)
                    return messages.slice(-messageDisplayLimit).map((msg: ChatMessage, i: number) => {
                      const actualIndex = offset + i
                      return (
                        <div key={`${msg.role}-${msg.timestamp}-${i}`}>
                          {msg.role === 'user' ? (
                            <div className="group/msg flex flex-col items-end">
                              <div className="max-w-[90%] sm:max-w-[85%]">
                                <div className="rounded-2xl sm:rounded-3xl bg-muted/60 px-3 py-2 sm:px-5 sm:py-3 shadow-sm border border-border/20">
                                  <div className="text-sm text-foreground whitespace-pre-wrap leading-relaxed break-words overflow-hidden">{msg.content}</div>
                                </div>
                                <MessageActions
                                  role="user"
                                  content={msg.content}
                                  messageIndex={actualIndex}
                                  conversationId={activeConversationId || ''}
                                  isStreaming={isStreaming}
                                  ttsAvailable={ttsAvailable}
                                  socket={socket}
                                  onEdit={onEdit}
                                  playTTS={playTTS}
                                  stopTTS={stopTTS}
                                  isTTSPlaying={isTTSPlaying}
                                />
                              </div>
                            </div>
                          ) : (
                            <div className="group/msg w-full overflow-hidden mb-4">
                              <div className="chat-text text-foreground break-words prose dark:prose-invert max-w-none prose-p:my-3 prose-li:my-1 prose-headings:mt-5 prose-headings:mb-2">
                                <Markdown>{msg.content}</Markdown>
                              </div>
                              <MessageActions
                                role="assistant"
                                content={msg.content}
                                messageIndex={actualIndex}
                                conversationId={activeConversationId || ''}
                                previousUserMessage={getPreviousUserMessage(actualIndex)}
                                isStreaming={isStreaming}
                                ttsAvailable={ttsAvailable}
                                socket={socket}
                                onEdit={() => {}}
                                playTTS={playTTS}
                                  stopTTS={stopTTS}
                                  isTTSPlaying={isTTSPlaying}
                              />
                            </div>
                          )}
                        </div>
                      )
                    })
                  })()}

                  {streamingContent && thinking ? (
                    <div className="group/msg w-full overflow-hidden">
                      <StreamingText content={streamingContent} isStreaming={true} />
                      <div className="flex items-center gap-2 mt-3 pb-1 opacity-50 hover:opacity-100 transition-opacity duration-500">
                        <div className="size-1.5 bg-primary rounded-full animate-pulse" />
                        <span className="text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground/80">
                          {status || 'Generating'}
                        </span>
                      </div>
                    </div>
                  ) : streamingContent ? (
                    <div className="group/msg w-full overflow-hidden">
                      <div className="chat-text text-foreground break-words prose dark:prose-invert max-w-none prose-p:my-3 prose-li:my-1 prose-headings:mt-5 prose-headings:mb-2">
                        <Markdown>{streamingContent}</Markdown>
                      </div>
                    </div>
                  ) : null}

                  {thinking && !streamingContent && (
                    <div className="flex items-center gap-2 py-3 animate-in fade-in duration-500">
                      <div className="flex gap-1">
                        <span className="h-2 w-2 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: '0ms', animationDuration: '1s' }} />
                        <span className="h-2 w-2 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: '200ms', animationDuration: '1s' }} />
                        <span className="h-2 w-2 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: '400ms', animationDuration: '1s' }} />
                      </div>
                      <span className="text-xs text-muted-foreground/60">
                        {status || 'Thinking...'}
                      </span>
                    </div>
                  )}

                  <ArtifactGallery
                    artifacts={artifacts}
                    onOpenArtifact={onOpenArtifact}
                  />
                </div>
              )}
            </div>
          )}
        </div>
        <ChatContainerScrollAnchor />
      </ChatContainerContent>
    </ChatContainerRoot>
  )
}
