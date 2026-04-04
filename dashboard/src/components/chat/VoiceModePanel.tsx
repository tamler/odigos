import { VoiceOrb } from '@/components/VoiceOrb'
import type { ChatMessage } from '@/layouts/AppLayout'

interface VoiceModePanelProps {
  messages: ChatMessage[]
  amplitude: number
  phase: string
  onExit: () => void
}

export function VoiceModePanel({ messages, amplitude, phase, onExit }: VoiceModePanelProps) {
  return (
    <div className="flex-1 flex flex-col h-full">
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4 opacity-40 hover:opacity-100 transition-opacity">
        {messages.slice(-5).map((msg: ChatMessage) => (
          <div key={msg.timestamp} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] rounded-2xl px-4 py-2 text-xs ${msg.role === 'user' ? 'bg-primary/20' : 'bg-muted/40'}`}>
              {msg.content}
            </div>
          </div>
        ))}
      </div>
      <VoiceOrb
        state={phase as any}
        amplitude={amplitude}
        onExit={onExit}
        onToggleMic={() => {}}
      />
    </div>
  )
}
