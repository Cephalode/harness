import { useState, useEffect } from 'react'
import Sidebar from './components/Sidebar'
import ActivityFeed from './components/ActivityFeed'
import SystemDiagram from './components/SystemDiagram'
import WorkerStatus from './components/WorkerStatus'
import StatusBar from './components/StatusBar'
import MessageInput from './components/MessageInput'
import { useWebSocket } from './hooks/useWebSocket'
import { useStatePolling } from './hooks/useStatePolling'
import { useDashboardStore } from './store'
import './App.css'

type ViewTab = 'activity' | 'diagram' | 'workers'

function App() {
  const [activeTab, setActiveTab] = useState<ViewTab>('activity')
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false)
  const connected = useDashboardStore((s) => s.connected)

  // Connect to WebSocket
  useWebSocket()

  // Poll StateStore REST API for persisted agent state
  useStatePolling()

  // Close mobile drawer on resize to desktop
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth >= 768) {
        setMobileDrawerOpen(false)
      }
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header
        className="border-b md:flex md:items-center md:justify-between md:px-4 md:py-2"
        style={{ borderColor: 'var(--border)', background: 'var(--bg-sidebar)' }}
      >
        {/* Mobile header: top row */}
        <div className="flex items-center justify-between px-3 py-2 md:hidden">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setMobileDrawerOpen(true)}
              className="text-gray-400 hover:text-white text-xl p-1 min-h-[44px] min-w-[44px] flex items-center justify-center"
              aria-label="Open sidebar"
            >
              ☰
            </button>
            <span className="text-white font-semibold text-sm">Harness</span>
          </div>
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-400' : 'bg-red-400'}`} />
            <span className="text-xs text-gray-500">{connected ? 'Live' : 'Disconnected'}</span>
          </div>
        </div>

        {/* Mobile header: tab row */}
        <div className="flex md:hidden border-t" style={{ borderColor: 'var(--border)' }}>
          <button
            onClick={() => setActiveTab('activity')}
            className={`flex-1 py-2.5 text-center text-sm font-medium min-h-[44px] ${
              activeTab === 'activity'
                ? 'text-blue-300 border-b-2 border-blue-400'
                : 'text-gray-500'
            }`}
          >
            Activity
          </button>
          <button
            onClick={() => setActiveTab('diagram')}
            className={`flex-1 py-2.5 text-center text-sm font-medium min-h-[44px] ${
              activeTab === 'diagram'
                ? 'text-blue-300 border-b-2 border-blue-400'
                : 'text-gray-500'
            }`}
          >
            Diagram
          </button>
          <button
            onClick={() => setActiveTab('workers')}
            className={`flex-1 py-2.5 text-center text-sm font-medium min-h-[44px] ${
              activeTab === 'workers'
                ? 'text-teal-300 border-b-2 border-teal-400'
                : 'text-gray-500'
            }`}
          >
            Workers
          </button>
        </div>

        {/* Desktop header: single row */}
        <div className="hidden md:flex items-center gap-3">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="text-gray-400 hover:text-white text-lg"
          >
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
        <div className="hidden md:flex items-center gap-2 text-sm">
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
          <button
            onClick={() => setActiveTab('workers')}
            className={`px-3 py-1 rounded ${activeTab === 'workers' ? 'bg-teal-900 text-teal-300' : 'text-gray-500 hover:text-gray-300'}`}
          >
            Workers
          </button>
        </div>
      </header>

      {/* Mobile drawer overlay */}
      {mobileDrawerOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
          {/* Backdrop */}
          <div
            className="drawer-backdrop absolute inset-0"
            onClick={() => setMobileDrawerOpen(false)}
          />
          {/* Drawer panel */}
          <div
            className="drawer-panel relative z-10 w-4/5 max-w-xs h-full overflow-y-auto border-r"
            style={{ borderColor: 'var(--border)', background: 'var(--bg-sidebar)' }}
          >
            {/* Drawer header */}
            <div className="flex items-center justify-between px-3 py-3 border-b" style={{ borderColor: 'var(--border)' }}>
              <span className="text-white font-semibold text-sm">Agent Teams</span>
              <button
                onClick={() => setMobileDrawerOpen(false)}
                className="text-gray-400 hover:text-white text-xl p-1 min-h-[44px] min-w-[44px] flex items-center justify-center"
                aria-label="Close sidebar"
              >
                ✕
              </button>
            </div>
            <Sidebar />
          </div>
        </div>
      )}

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Desktop sidebar */}
        {sidebarOpen && (
          <div
            className="hidden md:block w-64 border-r overflow-y-auto flex-shrink-0"
            style={{ borderColor: 'var(--border)', background: 'var(--bg-sidebar)' }}
          >
            <Sidebar />
          </div>
        )}
        <main className="flex-1 flex flex-col overflow-hidden">
          <div
            className="flex-1 overflow-y-auto p-2 md:p-4"
            style={{ background: 'var(--bg-primary)' }}
          >
            {activeTab === 'activity' ? <ActivityFeed /> : activeTab === 'diagram' ? <SystemDiagram /> : <WorkerStatus />}
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
