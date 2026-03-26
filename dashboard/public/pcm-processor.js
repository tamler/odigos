/**
 * AudioWorklet processor that captures microphone PCM and posts to main thread.
 * Based on Google ADK and VoiceStreamAI implementations.
 */
class PCMProcessor extends AudioWorkletProcessor {
  process(inputs) {
    if (inputs.length > 0 && inputs[0].length > 0) {
      // Post Float32Array to main thread
      this.port.postMessage(new Float32Array(inputs[0][0]))
    }
    return true
  }
}

registerProcessor('pcm-processor', PCMProcessor)
