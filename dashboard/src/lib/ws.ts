import { getApiKey } from './auth'

type MessageHandler = (msg: Record<string, unknown>) => void

export class ChatSocket {
  private ws: WebSocket | null = null
  private onMessage: MessageHandler
  private onStatusChange: (connected: boolean) => void
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null

  constructor(
    onMessage: MessageHandler,
    onStatusChange: (connected: boolean) => void,
  ) {
    this.onMessage = onMessage
    this.onStatusChange = onStatusChange
  }

  connect(): void {
    const token = getApiKey()
    if (!token) return

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    this.ws = new WebSocket(`${proto}//${window.location.host}/api/ws?token=${token}`)

    this.ws.onopen = () => this.onStatusChange(true)
    this.ws.onclose = () => {
      this.onStatusChange(false)
      this.scheduleReconnect()
    }
    this.ws.onmessage = (e) => {
      try {
        this.onMessage(JSON.parse(e.data))
      } catch { /* ignore parse errors */ }
    }
  }

  send(type: string, data: Record<string, unknown> = {}): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, ...data }))
    }
  }

  disconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.ws?.close()
    this.ws = null
  }

  private scheduleReconnect(): void {
    this.reconnectTimer = setTimeout(() => this.connect(), 3000)
  }
}
