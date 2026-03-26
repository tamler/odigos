import { Mic, MicOff, Volume2, Loader2 } from 'lucide-react'

export type VoiceState = 'idle' | 'listening' | 'processing' | 'thinking' | 'speaking'

interface VoiceOrbProps {
  state: VoiceState
  onExit: () => void
  onToggleMic: () => void
  amplitude?: number
}

export function VoiceOrb({ state, onExit, onToggleMic, amplitude = 0 }: VoiceOrbProps) {
  return (
    <div className="flex flex-col items-center justify-center p-8 space-y-12 animate-in fade-in zoom-in duration-500">
      {/* The Orb */}
      <div className="relative">
        {/* Glow Background */}
        <div className={`absolute inset-0 rounded-full blur-3xl opacity-20 transition-all duration-1000 ${
          state === 'listening' ? 'bg-primary scale-150' : 
          state === 'processing' ? 'bg-blue-500 scale-125' :
          state === 'thinking' ? 'bg-purple-500 scale-110 animate-pulse' :
          state === 'speaking' ? 'bg-emerald-500 scale-150' : 'bg-muted scale-100'
        }`} />

        {/* Amplitude Rings (Listening) */}
        {state === 'listening' && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div 
              className="absolute border-2 border-primary/30 rounded-full transition-all duration-75"
              style={{ width: `${120 + amplitude * 100}%`, height: `${120 + amplitude * 100}%` }}
            />
            <div 
              className="absolute border border-primary/20 rounded-full transition-all duration-150 delay-75"
              style={{ width: `${140 + amplitude * 80}%`, height: `${140 + amplitude * 80}%` }}
            />
          </div>
        )}

        {/* Main Body */}
        <button
          onClick={onToggleMic}
          className={`relative h-32 w-32 rounded-full flex items-center justify-center transition-all duration-500 shadow-2xl ${
            state === 'listening' ? 'bg-primary text-primary-foreground scale-110' :
            state === 'processing' ? 'bg-blue-600 text-white' :
            state === 'thinking' ? 'bg-purple-600 text-white' :
            state === 'speaking' ? 'bg-emerald-600 text-white scale-105' :
            'bg-muted text-muted-foreground'
          }`}
        >
          {state === 'listening' && <Mic className="h-10 w-10 animate-pulse" />}
          {state === 'processing' && <Loader2 className="h-10 w-10 animate-spin" />}
          {state === 'thinking' && <div className="h-10 w-10 border-4 border-white/30 border-t-white rounded-full animate-spin" />}
          {state === 'speaking' && <Volume2 className="h-10 w-10" />}
          {state === 'idle' && <MicOff className="h-10 w-10" />}
        </button>
      </div>

      {/* State Label */}
      <div className="text-center space-y-2">
        <p className="text-lg font-bold tracking-tight uppercase">
          {state === 'listening' ? 'Listening...' :
           state === 'processing' ? 'Transcribing...' :
           state === 'thinking' ? 'Thinking...' :
           state === 'speaking' ? 'Speaking...' : 'Microphone Off'}
        </p>
        <button 
          onClick={onExit}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors font-medium underline underline-offset-4"
        >
          Exit Voice Mode
        </button>
      </div>
    </div>
  )
}
