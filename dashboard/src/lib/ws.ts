type MessageHandler = (msg: Record<string, unknown>) => void

export class ChatSocket {
  private ws: WebSocket | null = null
  private baseHandler: MessageHandler
  private onStatusChange: (connected: boolean) => void
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectAttempt = 0
  private wasConnected = false
  private hidden = false

  // Public handler that pages can set/unset to receive messages
  onMessage: MessageHandler | null = null

  constructor(
    baseHandler: MessageHandler,
    onStatusChange: (connected: boolean) => void,
  ) {
    this.baseHandler = baseHandler
    this.onStatusChange = onStatusChange

    // Listen for tab visibility changes
    document.addEventListener('visibilitychange', this.handleVisibility)
  }

  private handleVisibility = () => {
    if (document.hidden) {
      this.hidden = true
    } else {
      this.hidden = false
      // Tab came back -- reconnect immediately if disconnected
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
        this.reconnectTimer = null
        this.connect()
      }
    }
  }

  connect(): void {
    // Don't reconnect while tab is hidden (OS will kill it anyway)
    if (this.hidden) return

    // Clean up any existing socket
    if (this.ws) {
      this.ws.onclose = null
      this.ws.onopen = null
      this.ws.onmessage = null
      this.ws.close()
      this.ws = null
    }

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    this.ws = new WebSocket(`${proto}//${window.location.host}/api/ws`)

    this.ws.onopen = () => {
      this.reconnectAttempt = 0
      this.wasConnected = true
      this.onStatusChange(true)
    }
    this.ws.onclose = () => {
      // Only notify disconnect if we were previously connected AND tab is visible
      // This prevents the toast flood on tab resume
      if (this.wasConnected && !this.hidden) {
        this.onStatusChange(false)
      }
      this.scheduleReconnect()
    }
    this.ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        this.baseHandler(msg)
        if (this.onMessage) this.onMessage(msg)
      } catch (err) { console.warn('[WS] Parse error:', err, e.data?.slice?.(0, 200)) }
    }
  }

  send(type: string, data: Record<string, unknown> = {}): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, ...data }))
    }
  }

  disconnect(): void {
    document.removeEventListener('visibilitychange', this.handleVisibility)
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.ws?.close()
    this.ws = null
  }

  private scheduleReconnect(): void {
    if (this.hidden) return // Don't bother reconnecting while hidden

    // Exponential backoff: 1s, 2s, 4s, 8s, max 30s
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempt), 30000)
    this.reconnectAttempt++
    this.reconnectTimer = setTimeout(() => this.connect(), delay)
  }
}
