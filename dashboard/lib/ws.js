export function createWsConnection(onMessage) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  let ws = null
  let sessionId = null
  let conversationId = null
  let reconnectTimer = null

  function connect() {
    ws = new WebSocket(`${proto}//${location.host}/api/ws`)

    ws.onopen = () => {
      onMessage({ type: '_connected' })
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'connected') {
        sessionId = data.session_id
        conversationId = data.conversation_id
      }
      onMessage(data)
    }

    ws.onclose = () => {
      onMessage({ type: '_disconnected' })
      reconnectTimer = setTimeout(connect, 3000)
    }

    ws.onerror = () => {
      ws.close()
    }
  }

  connect()

  return {
    send: (msg) => ws?.readyState === 1 && ws.send(JSON.stringify(msg)),
    sendChat: (content) => {
      const msg = { type: 'chat', content }
      if (conversationId) msg.conversation_id = conversationId
      ws?.readyState === 1 && ws.send(JSON.stringify(msg))
    },
    subscribe: (channels) => {
      ws?.readyState === 1 && ws.send(JSON.stringify({ type: 'subscribe', channels }))
    },
    getSessionId: () => sessionId,
    getConversationId: () => conversationId,
    close: () => {
      clearTimeout(reconnectTimer)
      ws?.close()
    },
  }
}
