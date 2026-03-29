import { Mic, MicOff, Loader2, Square } from 'lucide-react'
import { cn } from '@/lib/utils'

export type VoiceState = 'idle' | 'listening' | 'processing' | 'thinking' | 'speaking'

interface VoiceOrbProps {
  state: VoiceState
  onExit: () => void
  onToggleMic: () => void
  amplitude?: number
}

const WAVEFORM_DURATIONS = [1.05, 0.88, 1.22, 0.95, 1.12]

export function VoiceOrb({ state, onExit, onToggleMic, amplitude = 0 }: VoiceOrbProps) {
  // Map states to premium colors
  const stateColors = {
    idle: 'var(--muted)',
    listening: 'var(--primary)',
    processing: '#3b82f6', // blue-500
    thinking: '#8b5cf6',   // purple-500
    speaking: '#10b981',   // emerald-500
  }

  const activeColor = stateColors[state] || stateColors.idle

  return (
    <div className="flex flex-col items-center justify-center p-8 space-y-16 animate-in fade-in zoom-in duration-700 ease-[cubic-bezier(0.32,0.72,0,1)]">
      {/* The Orb Container */}
      <div className="relative group cursor-pointer" onClick={onToggleMic}>
        
        {/* Volumetric Glow Layers */}
        <div 
          className="absolute inset-0 rounded-full blur-[64px] opacity-20 transition-[background-color,opacity] duration-1000 ease-in-out scale-[2.5] animate-orb-glow"
          style={{ backgroundColor: activeColor }}
        />
        <div 
          className="absolute inset-0 rounded-full blur-[32px] opacity-30 transition-all duration-700 ease-in-out scale-[1.8]"
          style={{ backgroundColor: activeColor }}
        />

        {/* Amplitude Waves (Organic Rings) */}
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          {/* Layer 1 - Quickest response */}
          <div 
            className="absolute rounded-full border border-white/10 transition-transform duration-75 ease-out will-change-transform"
            style={{ 
              width: '100%', 
              height: '100%', 
              transform: `scale(${1 + amplitude * 1.5})`,
              backgroundColor: state === 'listening' ? `${activeColor}10` : 'transparent',
              borderColor: state === 'listening' ? `${activeColor}40` : 'transparent',
            }}
          />
          {/* Layer 2 - Smoother, larger */}
          <div 
            className="absolute rounded-full border border-white/5 transition-transform duration-150 ease-out will-change-transform"
            style={{ 
              width: '100%', 
              height: '100%', 
              transform: `scale(${1 + amplitude * 2.2})`,
              borderColor: state === 'listening' ? `${activeColor}20` : 'transparent',
            }}
          />
          {/* Layer 3 - Subtle outer glow */}
          <div 
            className="absolute rounded-full transition-all duration-300 ease-out blur-xl will-change-transform"
            style={{ 
              width: '100%', 
              height: '100%', 
              transform: `scale(${1 + amplitude * 1.2})`,
              backgroundColor: state === 'listening' ? `${activeColor}05` : 'transparent',
            }}
          />
        </div>

        {/* The Core Orb (Double-Bezel) */}
        <div className="relative p-1.5 rounded-full bg-white/5 border border-white/10 shadow-2xl backdrop-blur-sm transition-transform duration-500 group-hover:scale-105 active:scale-[0.97]">
          <div 
            className={cn(
              "h-32 w-32 rounded-full flex items-center justify-center transition-all duration-700 shadow-[inset_0_1px_1px_rgba(255,255,255,0.2)] relative overflow-hidden",
              state === 'idle' ? "bg-muted text-muted-foreground" : "text-white"
            )}
            style={{ backgroundColor: state !== 'idle' ? activeColor : undefined }}
          >
            {/* Glossy Overlay */}
            <div className="absolute inset-0 bg-gradient-to-tr from-black/20 to-white/20 pointer-events-none" />
            
            {/* Animated Icons/Content */}
            <div className="relative z-10 transition-all duration-500">
              {state === 'listening' && <Mic className="h-12 w-12 animate-pulse" />}
              {state === 'processing' && <Loader2 className="h-12 w-12 animate-spin" />}
              {state === 'thinking' && (
                <div className="flex gap-1.5 items-center">
                  <div className="h-2 w-2 rounded-full bg-white animate-bounce" style={{ animationDelay: '0ms' }} />
                  <div className="h-2 w-2 rounded-full bg-white animate-bounce" style={{ animationDelay: '150ms' }} />
                  <div className="h-2 w-2 rounded-full bg-white animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              )}
              {state === 'speaking' && (
                <div className="flex items-center gap-1 h-8">
                  {[...Array(5)].map((_, i) => (
                    <div 
                      key={i}
                      className="w-1.5 bg-white rounded-full animate-waveform"
                      style={{ 
                        height: '100%',
                        animationDelay: `${i * 0.15}s`,
                        animationDuration: `${WAVEFORM_DURATIONS[i]}s`
                      }}
                    />
                  ))}
                </div>
              )}
              {state === 'idle' && <MicOff className="h-12 w-12" />}
            </div>
          </div>
        </div>
      </div>

      {/* Action Area */}
      <div className="text-center space-y-8 max-w-xs">
        <div className="space-y-2 px-6 py-3 rounded-2xl bg-muted/30 border border-white/5 backdrop-blur-md">
          <p className="text-sm font-bold tracking-[0.2em] uppercase text-primary/80">
            {state === 'listening' ? 'Listening' :
             state === 'processing' ? 'Transcribing' :
             state === 'thinking' ? 'Thinking' :
             state === 'speaking' ? 'Speaking' : 'Muted'}
          </p>
          <p className="text-xs text-muted-foreground font-medium italic opacity-60">
            {state === 'listening' ? "Go ahead, I'm all ears" :
             state === 'processing' ? "Turning voice into words..." :
             state === 'thinking' ? "Processing your request..." :
             state === 'speaking' ? "Just a moment..." : "Click to unmute"}
          </p>
        </div>

        <div className="flex flex-col items-center gap-4 pt-4">
          <button 
            onClick={onExit}
            className="group flex items-center gap-2 px-6 py-2.5 rounded-full bg-destructive/10 text-destructive border border-destructive/20 hover:bg-destructive/20 transition-all duration-300 text-xs font-bold uppercase tracking-widest"
          >
            <Square className="h-3 w-3 fill-current group-hover:scale-110 transition-transform" />
            Exit Voice Mode
          </button>
        </div>
      </div>
    </div>
  )
}
