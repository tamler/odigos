/**
 * Voice mode hook: continuous listen → detect silence → transcribe → send → repeat.
 *
 * Uses MediaRecorder for capture + AnalyserNode for silence detection
 * and amplitude visualization. Adaptive silence threshold calibrates
 * to ambient noise on start.
 *
 * All HTTP through api.ts. Error feedback via custom events.
 */
import { useCallback, useRef, useState } from 'react'
import { postFormRaw } from '@/lib/api'
import { hasSpeechEnergy } from '@/lib/audio-utils'

const SILENCE_DURATION = 1500
const MIN_RECORDING_MS = 800
const FFT_SIZE = 2048
const SMOOTHING = 0.85
const CALIBRATION_MS = 600
const THRESHOLD_MULTIPLIER = 2.5

export type VoicePhase = 'idle' | 'listening' | 'processing' | 'thinking' | 'speaking'

interface UseVoiceModeOptions {
  onTranscription: (text: string) => void
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
  const recordingStartRef = useRef<number>(0)
  const activeRef = useRef(false)
  const smoothedVolumeRef = useRef(0)
  const silenceThresholdRef = useRef(0.01)
  const isTranscribingRef = useRef(false)

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
    if (blob.size < 1000) return
    const hasEnergy = await hasSpeechEnergy(blob)
    if (!hasEnergy) return
    isTranscribingRef.current = true
    setPhase('processing')
    try {
      const formData = new FormData()
      const ext = blob.type.includes('mp4') ? 'mp4' : blob.type.includes('ogg') ? 'ogg' : 'webm'
      formData.append('audio', blob, `recording.${ext}`)
      const res = await postFormRaw('/api/audio/transcribe', formData)
      if (res.ok) {
        const data = await res.json()
        if (data.text && data.text.trim()) {
          onTranscription(data.text.trim())
        }
      }
    } catch (err) {
      console.error('Voice transcription failed:', err)
    } finally {
      isTranscribingRef.current = false
    }
  }, [onTranscription, setPhase])

  const getSupportedMimeType = useCallback((): string => {
    return ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg']
      .find(m => MediaRecorder.isTypeSupported(m)) || ''
  }, [])

  const createRecorder = useCallback(() => {
    if (!streamRef.current) return null
    const mimeType = getSupportedMimeType()
    return new MediaRecorder(streamRef.current, mimeType ? { mimeType } : {})
  }, [getSupportedMimeType])

  const startListening = useCallback(() => {
    const recorder = recorderRef.current
    if (!recorder || !activeRef.current) return
    chunksRef.current = []
    silenceStartRef.current = null
    recordingStartRef.current = Date.now()
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data)
    }
    recorder.start(250)
    setPhase('listening')
  }, [setPhase])

  const handleSpeechEnd = useCallback(async () => {
    if (!activeRef.current || isTranscribingRef.current) return
    const blob = await stopCurrentRecording()
    if (blob && blob.size > 1000) {
      await transcribeAndSend(blob)
    }
    if (activeRef.current && streamRef.current) {
      const newRecorder = createRecorder()
      if (newRecorder) {
        recorderRef.current = newRecorder
        startListening()
      }
    }
  }, [stopCurrentRecording, transcribeAndSend, createRecorder, startListening])

  const monitorLoop = useCallback(() => {
    const analyser = analyserRef.current
    if (!analyser || !activeRef.current) return

    const dataArray = new Float32Array(FFT_SIZE)
    analyser.getFloatTimeDomainData(dataArray)

    let sumSquares = 0
    for (let i = 0; i < dataArray.length; i++) sumSquares += dataArray[i] * dataArray[i]
    const rms = Math.sqrt(sumSquares / dataArray.length)

    const threshold = silenceThresholdRef.current
    const normalized = Math.max(0, Math.min(1, (rms - threshold * 0.5) / (0.3 - threshold * 0.5)))
    smoothedVolumeRef.current = SMOOTHING * smoothedVolumeRef.current + (1 - SMOOTHING) * normalized
    onAmplitudeChange?.(smoothedVolumeRef.current)

    const recorder = recorderRef.current
    if (recorder && recorder.state === 'recording' && !isTranscribingRef.current) {
      const elapsed = Date.now() - recordingStartRef.current
      if (rms < threshold) {
        if (silenceStartRef.current === null) {
          silenceStartRef.current = Date.now()
        } else if (Date.now() - silenceStartRef.current > SILENCE_DURATION && elapsed > MIN_RECORDING_MS) {
          silenceStartRef.current = null
          handleSpeechEnd()
          return
        }
      } else {
        silenceStartRef.current = null
      }
    }

    animFrameRef.current = requestAnimationFrame(monitorLoop)
  }, [onAmplitudeChange, handleSpeechEnd])

  const calibrateThreshold = useCallback((analyser: AnalyserNode): Promise<number> => {
    return new Promise((resolve) => {
      const samples: number[] = []
      const dataArray = new Float32Array(FFT_SIZE)
      const start = Date.now()
      function sample() {
        if (Date.now() - start > CALIBRATION_MS) {
          const avgRms = samples.length > 0 ? samples.reduce((a, b) => a + b) / samples.length : 0.01
          resolve(Math.max(0.005, avgRms * THRESHOLD_MULTIPLIER))
          return
        }
        analyser.getFloatTimeDomainData(dataArray)
        let sum = 0
        for (let i = 0; i < dataArray.length; i++) sum += dataArray[i] * dataArray[i]
        samples.push(Math.sqrt(sum / dataArray.length))
        requestAnimationFrame(sample)
      }
      sample()
    })
  }, [])

  const enter = useCallback(async () => {
    try {
      // Create AudioContext synchronously on user gesture (iOS requirement)
      const ctx = new AudioContext()
      audioCtxRef.current = ctx

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
      streamRef.current = stream
      if (ctx.state === 'suspended') await ctx.resume()

      const source = ctx.createMediaStreamSource(stream)
      const analyser = ctx.createAnalyser()
      analyser.fftSize = FFT_SIZE
      analyser.smoothingTimeConstant = 0.3
      source.connect(analyser)
      analyserRef.current = analyser

      const recorder = createRecorder()
      if (!recorder) throw new Error('MediaRecorder not available')
      recorderRef.current = recorder

      silenceThresholdRef.current = await calibrateThreshold(analyser)

      activeRef.current = true
      setActive(true)
      startListening()
      animFrameRef.current = requestAnimationFrame(monitorLoop)
    } catch (err) {
      console.error('Failed to start voice mode:', err)
      if (audioCtxRef.current) {
        audioCtxRef.current.close().catch(() => {})
        audioCtxRef.current = null
      }
      setActive(false)
      activeRef.current = false
      const msg = err instanceof DOMException && err.name === 'NotAllowedError'
        ? 'Microphone access denied. Check your browser permissions.'
        : 'Voice mode failed to start. Try again.'
      window.dispatchEvent(new CustomEvent('voice-error', { detail: msg }))
    }
  }, [startListening, monitorLoop, calibrateThreshold, createRecorder])

  const exit = useCallback(async () => {
    activeRef.current = false
    setActive(false)
    setPhase('idle')
    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current)
    if (recorderRef.current && recorderRef.current.state !== 'inactive') recorderRef.current.stop()
    recorderRef.current = null
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop())
      streamRef.current = null
    }
    if (audioCtxRef.current) {
      await audioCtxRef.current.close().catch(() => {})
      audioCtxRef.current = null
    }
    analyserRef.current = null
    onAmplitudeChange?.(0)
  }, [setPhase, onAmplitudeChange])

  return { active, phase, enter, exit, setPhase }
}
