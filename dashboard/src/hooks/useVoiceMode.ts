/**
 * Voice mode hook: continuous listen → transcribe → send → TTS → repeat.
 *
 * Uses MediaRecorder for capture + AnalyserNode for silence detection
 * and amplitude visualization. Both share the same getUserMedia stream.
 */
import { useCallback, useRef, useState } from 'react'

const SILENCE_THRESHOLD = 0.01  // RMS below this = silent
const SILENCE_DURATION = 1500   // ms of silence before auto-stop
const MIN_RECORDING_MS = 500    // don't send recordings shorter than this
const FFT_SIZE = 2048
const SMOOTHING = 0.85

export type VoicePhase = 'idle' | 'listening' | 'processing' | 'thinking' | 'speaking'

interface UseVoiceModeOptions {
  onTranscription: (text: string) => void  // called with transcribed text
  onPhaseChange?: (phase: VoicePhase) => void
  onAmplitudeChange?: (amplitude: number) => void
}

export function useVoiceMode({ onTranscription, onPhaseChange, onAmplitudeChange }: UseVoiceModeOptions) {
  const [active, setActive] = useState(false)
  const [phase, setPhaseState] = useState<VoicePhase>('idle')

  const streamRef = useRef<MediaStream | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const animFrameRef = useRef<number>(0)
  const chunksRef = useRef<Blob[]>([])
  const silenceStartRef = useRef<number | null>(null)
  const isSpeakingRef = useRef(false)
  const recordingStartRef = useRef<number>(0)
  const activeRef = useRef(false)
  const smoothedVolumeRef = useRef(0)

  const setPhase = useCallback((p: VoicePhase) => {
    setPhaseState(p)
    onPhaseChange?.(p)
  }, [onPhaseChange])

  const stopCurrentRecording = useCallback(async (): Promise<Blob | null> => {
    const recorder = recorderRef.current
    if (!recorder || recorder.state === 'inactive') return null

    return new Promise((resolve) => {
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
        chunksRef.current = []
        resolve(blob)
      }
      recorder.stop()
    })
  }, [])

  const transcribeAndSend = useCallback(async (blob: Blob) => {
    if (blob.size < 1000) return  // too short

    setPhase('processing')
    try {
      const formData = new FormData()
      const ext = blob.type.includes('mp4') ? 'mp4' : blob.type.includes('ogg') ? 'ogg' : 'webm'
      formData.append('audio', blob, `recording.${ext}`)

      const res = await fetch('/api/audio/transcribe', {
        method: 'POST',
        credentials: 'include',
        body: formData,
      })
      if (res.ok) {
        const data = await res.json()
        if (data.text && data.text.trim()) {
          onTranscription(data.text.trim())
        }
      }
    } catch (err) {
      console.error('Voice transcription failed:', err)
    }
  }, [onTranscription, setPhase])

  const startListening = useCallback(() => {
    const recorder = recorderRef.current
    const stream = streamRef.current
    if (!recorder || !stream || !activeRef.current) return

    // Reset state
    chunksRef.current = []
    silenceStartRef.current = null
    isSpeakingRef.current = false
    recordingStartRef.current = Date.now()

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data)
    }

    // Don't set onstop here — it gets set in stopCurrentRecording
    recorder.start(250)
    setPhase('listening')
  }, [setPhase])

  const monitorLoop = useCallback(() => {
    const analyser = analyserRef.current
    if (!analyser || !activeRef.current) return

    const dataArray = new Float32Array(FFT_SIZE)
    analyser.getFloatTimeDomainData(dataArray)

    // Calculate RMS
    let sumSquares = 0
    for (let i = 0; i < dataArray.length; i++) {
      sumSquares += dataArray[i] * dataArray[i]
    }
    const rms = Math.sqrt(sumSquares / dataArray.length)

    // Normalized amplitude for orb animation (0-1)
    const normalized = Math.max(0, Math.min(1, (rms - 0.005) / (0.3 - 0.005)))
    smoothedVolumeRef.current = SMOOTHING * smoothedVolumeRef.current + (1 - SMOOTHING) * normalized
    onAmplitudeChange?.(smoothedVolumeRef.current)

    // Silence detection (only when recorder is active)
    const recorder = recorderRef.current
    if (recorder && recorder.state === 'recording') {
      const elapsed = Date.now() - recordingStartRef.current

      if (rms < SILENCE_THRESHOLD) {
        if (silenceStartRef.current === null) {
          silenceStartRef.current = Date.now()
        } else if (
          Date.now() - silenceStartRef.current > SILENCE_DURATION &&
          elapsed > MIN_RECORDING_MS
        ) {
          // User stopped speaking — process recording
          isSpeakingRef.current = false
          silenceStartRef.current = null

          stopCurrentRecording().then(async (blob) => {
            if (blob && blob.size > 1000) {
              await transcribeAndSend(blob)
            }
            // Restart listening and monitoring if still active
            if (activeRef.current && streamRef.current) {
              const newRecorder = new MediaRecorder(streamRef.current, {
                mimeType: MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
                  ? 'audio/webm;codecs=opus' : 'audio/webm',
              })
              recorderRef.current = newRecorder
              startListening()
              // Restart the monitoring loop
              animFrameRef.current = requestAnimationFrame(monitorLoop)
            }
          })
          // Pause monitoring during transcription — resumes in the .then()
          return
        }
      } else {
        silenceStartRef.current = null
        if (!isSpeakingRef.current) {
          isSpeakingRef.current = true
        }
      }
    }

    animFrameRef.current = requestAnimationFrame(monitorLoop)
  }, [onAmplitudeChange, stopCurrentRecording, transcribeAndSend, startListening])

  const enter = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
      streamRef.current = stream

      // Set up AnalyserNode
      const ctx = new AudioContext()
      if (ctx.state === 'suspended') await ctx.resume()
      audioCtxRef.current = ctx
      const source = ctx.createMediaStreamSource(stream)
      const analyser = ctx.createAnalyser()
      analyser.fftSize = FFT_SIZE
      analyser.smoothingTimeConstant = 0.3
      source.connect(analyser)
      analyserRef.current = analyser

      // Set up MediaRecorder
      const recorder = new MediaRecorder(stream, {
        mimeType: MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
          ? 'audio/webm;codecs=opus' : 'audio/webm',
      })
      recorderRef.current = recorder

      activeRef.current = true
      setActive(true)
      localStorage.setItem('odigos-voice-mode', 'true')

      // Start the monitoring loop and recording
      startListening()
      animFrameRef.current = requestAnimationFrame(monitorLoop)
    } catch {
      console.error('Failed to start voice mode')
    }
  }, [startListening, monitorLoop])

  const exit = useCallback(async () => {
    activeRef.current = false
    setActive(false)
    setPhase('idle')
    localStorage.setItem('odigos-voice-mode', 'false')

    cancelAnimationFrame(animFrameRef.current)

    // Stop recorder if active
    if (recorderRef.current && recorderRef.current.state !== 'inactive') {
      recorderRef.current.stop()
    }
    recorderRef.current = null

    // Close audio context
    if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
      audioCtxRef.current.close()
    }
    audioCtxRef.current = null
    analyserRef.current = null

    // Stop mic stream
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop())
      streamRef.current = null
    }

    smoothedVolumeRef.current = 0
    onAmplitudeChange?.(0)
  }, [setPhase, onAmplitudeChange])

  return {
    active,
    phase,
    enter,
    exit,
    // Allow external phase changes (e.g., set to 'thinking' when agent is processing)
    setPhase,
  }
}
