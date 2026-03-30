/**
 * Voice mode hook: continuous listen → detect speech end → transcribe → send → repeat.
 *
 * Uses Silero VAD (via @ricky0123/vad-web) for speech detection instead of
 * RMS amplitude. VAD detects actual human speech, not just loudness -- works
 * in noisy environments, ignores keyboard typing, AC hum, etc.
 *
 * Falls back to RMS-based detection if VAD fails to load.
 */
import { useCallback, useRef, useState } from 'react'
import { postFormRaw } from '@/lib/api'

const FFT_SIZE = 2048
const SMOOTHING = 0.85

// RMS fallback constants (used if VAD unavailable)
const SILENCE_DURATION = 1500
const MIN_RECORDING_MS = 800
const CALIBRATION_MS = 600
const THRESHOLD_MULTIPLIER = 2.5

export type VoicePhase = 'idle' | 'listening' | 'processing' | 'thinking' | 'speaking'

/** Convert Float32Array PCM to WAV blob */
function float32ToWav(samples: Float32Array, sampleRate: number): Blob {
  const numChannels = 1
  const bitsPerSample = 16
  const byteRate = sampleRate * numChannels * (bitsPerSample / 8)
  const blockAlign = numChannels * (bitsPerSample / 8)
  const dataSize = samples.length * (bitsPerSample / 8)
  const buffer = new ArrayBuffer(44 + dataSize)
  const view = new DataView(buffer)

  // WAV header
  const writeString = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i))
  }
  writeString(0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true)
  writeString(8, 'WAVE')
  writeString(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, numChannels, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, byteRate, true)
  view.setUint16(32, blockAlign, true)
  view.setUint16(34, bitsPerSample, true)
  writeString(36, 'data')
  view.setUint32(40, dataSize, true)

  // PCM data
  let offset = 44
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true)
    offset += 2
  }

  return new Blob([buffer], { type: 'audio/wav' })
}

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
  const vadRef = useRef<any>(null)
  const useVadRef = useRef(false)

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
    const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg']
    return candidates.find(m => MediaRecorder.isTypeSupported(m)) || ''
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

  // Called by VAD when speech ends
  const handleSpeechEnd = useCallback(async () => {
    if (!activeRef.current || isTranscribingRef.current) return

    const blob = await stopCurrentRecording()
    if (blob && blob.size > 1000) {
      await transcribeAndSend(blob)
    }

    // Restart recording if still active
    if (activeRef.current && streamRef.current) {
      const newRecorder = createRecorder()
      if (newRecorder) {
        recorderRef.current = newRecorder
        startListening()
      }
    }
  }, [stopCurrentRecording, transcribeAndSend, createRecorder, startListening])

  // RMS monitoring loop (fallback when VAD unavailable)
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

  // Amplitude-only monitoring (when VAD handles speech detection)
  const amplitudeLoop = useCallback(() => {
    const analyser = analyserRef.current
    if (!analyser || !activeRef.current) return

    const dataArray = new Float32Array(FFT_SIZE)
    analyser.getFloatTimeDomainData(dataArray)

    let sumSquares = 0
    for (let i = 0; i < dataArray.length; i++) sumSquares += dataArray[i] * dataArray[i]
    const rms = Math.sqrt(sumSquares / dataArray.length)

    const normalized = Math.max(0, Math.min(1, (rms - 0.005) / 0.295))
    smoothedVolumeRef.current = SMOOTHING * smoothedVolumeRef.current + (1 - SMOOTHING) * normalized
    onAmplitudeChange?.(smoothedVolumeRef.current)

    animFrameRef.current = requestAnimationFrame(amplitudeLoop)
  }, [onAmplitudeChange])

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

      // Set up AnalyserNode (for amplitude visualization)
      const source = ctx.createMediaStreamSource(stream)
      const analyser = ctx.createAnalyser()
      analyser.fftSize = FFT_SIZE
      analyser.smoothingTimeConstant = 0.3
      source.connect(analyser)
      analyserRef.current = analyser

      // Try to initialize Silero VAD
      let vadAvailable = false
      try {
        const { MicVAD } = await import('@ricky0123/vad-web')
        const vad = await MicVAD.new({
          onSpeechEnd: async (audio: Float32Array) => {
            if (!activeRef.current || isTranscribingRef.current) return
            // Convert Float32Array to WAV blob
            const wavBlob = float32ToWav(audio, 16000)
            if (wavBlob.size > 1000) {
              await transcribeAndSend(wavBlob)
            }
            if (activeRef.current) setPhase('listening')
          },
          positiveSpeechThreshold: 0.8,
          negativeSpeechThreshold: 0.3,
        })
        vad.start()
        vadRef.current = vad
        useVadRef.current = true
        vadAvailable = true
        console.log('[Voice] Silero VAD active')
      } catch (err) {
        console.warn('[Voice] VAD unavailable, falling back to RMS:', err)
        useVadRef.current = false
      }

      activeRef.current = true
      setActive(true)

      if (vadAvailable) {
        // VAD handles speech detection and gives us audio directly -- no MediaRecorder needed
        setPhase('listening')
        animFrameRef.current = requestAnimationFrame(amplitudeLoop)
      } else {
        // Fallback: RMS-based silence detection with MediaRecorder
        const recorder = createRecorder()
        if (!recorder) throw new Error('MediaRecorder not available')
        recorderRef.current = recorder
        silenceThresholdRef.current = await calibrateThreshold(analyser)
        startListening()
        animFrameRef.current = requestAnimationFrame(monitorLoop)
      }
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
  }, [startListening, monitorLoop, amplitudeLoop, calibrateThreshold, createRecorder, handleSpeechEnd])

  const exit = useCallback(async () => {
    activeRef.current = false
    setActive(false)
    setPhase('idle')

    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current)

    // Stop VAD
    if (vadRef.current) {
      vadRef.current.destroy?.() || vadRef.current.pause?.()
      vadRef.current = null
    }

    if (recorderRef.current && recorderRef.current.state !== 'inactive') {
      recorderRef.current.stop()
    }
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
    useVadRef.current = false
    onAmplitudeChange?.(0)
  }, [setPhase, onAmplitudeChange])

  return { active, phase, enter, exit, setPhase }
}
