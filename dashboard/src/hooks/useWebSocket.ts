import { useEffect, useRef, useCallback } from 'react'
import { useDashboardStore } from '../store'

export function useWebSocket(url: string = `ws://${window.location.host}/ws`) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const setConnected = useDashboardStore((s) => s.setConnected)
  const setTeamData = useDashboardStore((s) => s.setTeamData)
  const addEvent = useDashboardStore((s) => s.addEvent)

  const connect = useCallback(() => {
    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        console.log('[WS] Connected to harness dashboard')
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)

          if (data.type === 'init') {
            // Initial team tree
            setTeamData(data.data)
          } else {
            // HarnessEvent
            addEvent(data)
          }
        } catch (err) {
          console.error('[WS] Parse error:', err)
        }
      }

      ws.onclose = () => {
        setConnected(false)
        console.log('[WS] Disconnected, reconnecting in 2s...')
        reconnectTimer.current = setTimeout(connect, 2000)
      }

      ws.onerror = (err) => {
        console.error('[WS] Error:', err)
        ws.close()
      }
    } catch (err) {
      console.error('[WS] Connection failed:', err)
      reconnectTimer.current = setTimeout(connect, 2000)
    }
  }, [url, setConnected, setTeamData, addEvent])

  useEffect(() => {
    connect()
    return () => {
      wsRef.current?.close()
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
    }
  }, [connect])

  return wsRef
}
