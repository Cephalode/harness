import { useState } from 'react'

export default function MessageInput() {
  const [message, setMessage] = useState('')

  const handleSend = async () => {
    if (!message.trim()) return
    try {
      await fetch('/api/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      })
      setMessage('')
    } catch (err) {
      console.error('Failed to send message:', err)
    }
  }

  return (
    <div className="border-t px-4 py-3" style={{ borderColor: 'var(--border)', background: 'var(--bg-sidebar)' }}>
      <div className="flex gap-2">
        <input
          type="text"
          value={message}
          onChange={e => setMessage(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSend()}
          placeholder="Send a message to the orchestrator..."
          className="flex-1 px-3 py-2 rounded text-sm outline-none"
          style={{ background: 'var(--bg-primary)', color: 'var(--text-primary)', border: '1px solid var(--border)' }}
        />
        <button
          onClick={handleSend}
          className="px-4 py-2 rounded text-sm font-medium"
          style={{ background: 'var(--accent-blue)', color: 'var(--text-primary)' }}
        >
          Send
        </button>
      </div>
    </div>
  )
}
