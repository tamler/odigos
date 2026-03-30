/**
 * Shared audio utilities for voice input.
 *
 * hasSpeechEnergy: decodes an audio blob and checks if it contains
 * signal above a threshold. Prevents sending silence to Groq.
 */

const ENERGY_THRESHOLD = 0.01  // RMS below this = silence

export async function hasSpeechEnergy(blob: Blob): Promise<boolean> {
  try {
    const arrayBuffer = await blob.arrayBuffer()
    const ctx = new OfflineAudioContext(1, 1, 16000)

    let audioBuffer: AudioBuffer
    try {
      audioBuffer = await ctx.decodeAudioData(arrayBuffer)
    } catch {
      // Can't decode (unsupported format) -- assume it has speech
      return true
    }

    const samples = audioBuffer.getChannelData(0)
    let sumSquares = 0
    for (let i = 0; i < samples.length; i++) {
      sumSquares += samples[i] * samples[i]
    }
    const rms = Math.sqrt(sumSquares / samples.length)

    return rms > ENERGY_THRESHOLD
  } catch {
    // Any failure -- assume speech, don't block
    return true
  }
}
