/**
 * Shared audio system for TTS playback.
 *
 * Single source of truth for all TTS state. One audio element,
 * one set of controls. Used by AppLayout, passed to children
 * via outlet context. No duplicates.
 */
import { useCallback, useRef, useState } from 'react'

export function useAudio() {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [playing, setPlaying] = useState(false)

  const play = useCallback(async (text: string) => {
    // Stop any current playback first
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.src = ''
      audioRef.current = null
      setPlaying(false)
    }
    if (!text) return

    try {
      const res = await fetch(`/api/audio/speak?text=${encodeURIComponent(text)}`, {
        credentials: 'include',
      })
      if (!res.ok) return
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audioRef.current = audio
      setPlaying(true)
      audio.onended = () => {
        URL.revokeObjectURL(url)
        audioRef.current = null
        setPlaying(false)
      }
      audio.onerror = () => {
        URL.revokeObjectURL(url)
        audioRef.current = null
        setPlaying(false)
      }
      await audio.play()
    } catch {
      setPlaying(false)
    }
  }, [])

  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.src = ''
      audioRef.current = null
    }
    setPlaying(false)
  }, [])

  return { play, stop, playing }
}
