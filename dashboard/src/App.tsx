import { useState } from 'react'
import Sidebar from './components/Sidebar'
import ActivityFeed from './components/ActivityFeed'
import SystemDiagram from './components/SystemDiagram'
import StatusBar from './components/StatusBar'
import MessageInput from './components/MessageInput'
import { useWebSocket } from './hooks/useWebSocket'
import { useDashboardStore } from './store'
import './App.css'

type ViewTab = 'activity' | 'diagram'

function App() {
  const [activeTab, setActiveTab] = useState<ViewTab>('activity')
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const connected = useDashboardStore((s) => s.connected)

  // Connect to WebSocket
  useWebSocket()

  return (
    <div className="flex flex-col h-screen">
      {/* Top bar */}
      <header className="flex items-center justify-between px-4 py-2 border-b"
              style={{ borderColor: 'var(--border)', background: 'var(--bg-sidebar)' }}>
        <div className="flex items-center gap-3">
          <button onClick={() => setSidebarOpen(!sidebarOpen)}
                  className="text-gray-400 hover:text-white text-lg">
            ☰
          </button>
          <nav className="text-sm">
            <span className="text-gray-500">Workspace</span>
            <span className="text-gray-600 mx-1">/</span>
            <span className="text-gray-400">Harness</span>
            <span className="text-gray-600 mx-1">/</span>
            <span className="text-white">Dashboard</span>
          </nav>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-400' : 'bg-red-400'}`} />
          <span className="text-xs text-gray-500">{connected ? 'Live' : 'Disconnected'}</span>
          <span className="mx-2 text-gray-700">|</span>
          <button
            onClick={() => setActiveTab('activity')}
            className={`px-3 py-1 rounded ${activeTab === 'activity' ? 'bg-blue-900 text-blue-300' : 'text-gray-500 hover:text-gray-300'}`}
          >
            Activity
          </button>
          <button
            onClick={() => setActiveTab('diagram')}
            className={`px-3 py-1 rounded ${activeTab === 'diagram' ? 'bg-blue-900 text-blue-300' : 'text-gray-500 hover:text-gray-300'}`}
          >
            Diagram
          </button>
        </div>
      </header>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {sidebarOpen && (
          <div className="w-64 border-r overflow-y-auto flex-shrink-0"
               style={{ borderColor: 'var(--border)', background: 'var(--bg-sidebar)' }}>
            <Sidebar />
          </div>
        )}
        <main className="flex-1 flex flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto p-4"
               style={{ background: 'var(--bg-primary)' }}>
            {activeTab === 'activity' ? <ActivityFeed /> : <SystemDiagram />}
          </div>
          <MessageInput />
        </main>
      </div>

      {/* Status bar */}
      <StatusBar />
    </div>
  )
}

export default App
