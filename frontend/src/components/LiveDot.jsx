export default function LiveDot({ connected, label }) {
  return (
    <span className={`live-dot${connected ? ' on' : ''}`}>
      <span className="pulse" />
      {label || (connected ? 'Live' : 'Connecting…')}
    </span>
  )
}
