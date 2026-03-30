/**
 * Push-to-talk: hold mic button → record → release → transcribe → return text.
 * For quick voice input, not continuous conversation mode.
 */
import { useCallback, useRef, useState } from 'react'
import { postFormRaw } from '@/lib/api'

export function usePushToTalk(onResult: (text: string) => void) {
  const [recording, setRecording] = useState(false)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])

  const start = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
      streamRef.current = stream

      const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg']
        .find(m => MediaRecorder.isTypeSupported(m)) || ''
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {})
      recorderRef.current = recorder
      chunksRef.current = []

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }

      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
        chunksRef.current = []

        // Clean up stream
        stream.getTracks().forEach(t => t.stop())
        streamRef.current = null
        recorderRef.current = null
        setRecording(false)

        if (blob.size < 1000) return

        // Transcribe
        const formData = new FormData()
        const ext = blob.type.includes('mp4') ? 'mp4' : blob.type.includes('ogg') ? 'ogg' : 'webm'
        formData.append('audio', blob, `recording.${ext}`)
        try {
          const res = await postFormRaw('/api/audio/transcribe', formData)
          if (res.ok) {
            const data = await res.json()
            if (data.text && data.text.trim()) {
              onResult(data.text.trim())
            }
          }
        } catch (err) {
          console.error('Push-to-talk transcription failed:', err)
        }
      }

      recorder.start(250)
      setRecording(true)
    } catch (err) {
      console.error('Push-to-talk failed:', err)
      setRecording(false)
      const msg = err instanceof DOMException && err.name === 'NotAllowedError'
        ? 'Microphone access denied.'
        : 'Voice input failed.'
      window.dispatchEvent(new CustomEvent('voice-error', { detail: msg }))
    }
  }, [onResult])

  const stop = useCallback(() => {
    if (recorderRef.current && recorderRef.current.state === 'recording') {
      recorderRef.current.stop()
    }
  }, [])

  return { recording, start, stop }
}
