export default function StatusBar() {
  return (
    <footer className="flex items-center justify-between px-4 py-1.5 text-xs border-t"
            style={{ borderColor: 'var(--border)', background: 'var(--bg-sidebar)' }}>
      <div className="flex items-center gap-4 text-gray-500">
        <span>Session: ---</span>
        <span>Duration: 0m 00s</span>
      </div>
      <div className="flex items-center gap-4 text-gray-500">
        <span>Cost: $0.0000</span>
        <span>Tokens: 0 in / 0 out</span>
      </div>
    </footer>
  )
}
