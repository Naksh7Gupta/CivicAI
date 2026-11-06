import { useEffect, useMemo, useState } from 'react'

type Pothole = {
  id: string
  image_url: string
  timestamp: string
  latitude: number | null
  longitude: number | null
  confidence: number
  severity: 'Unassessed'
  address: string
  status: 'Needs review' | 'Reported' | 'Monitoring'
}

const icon = (name: string) => {
  const paths: Record<string, string> = {
    grid: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z',
    map: 'M3 6.5 9 4l6 2.5L21 4v13.5L15 20l-6-2.5L3 20V6.5Z M9 4v13.5M15 6.5V20',
    image: 'M4 5h16v14H4z M7 15l3-3 2 2 2-2 3 3 M8 9h.01',
    chart: 'M4 19V5M4 19h17M8 16v-4M12 16V8M16 16v-7',
    settings: 'M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3.9a7.4 7.4 0 0 0-2-1.2L14.3 3h-4.1l-.4 2.6a7.4 7.4 0 0 0-2 1.2l-2.3-.9-2 3.4 2 1.5a7 7 0 0 0 0 2.4l-2 1.5 2 3.4 2.3-.9a7.4 7.4 0 0 0 2 1.2l.4 2.6h4.1l.4-2.6a7.4 7.4 0 0 0 2-1.2l2.3.9 2-3.4-2-1.5c.1-.4.1-.8.1-1.2Z',
    bell: 'M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4',
    search: 'm20 20-4-4M11 18a7 7 0 1 1 0-14 7 7 0 0 1 0 14Z',
    download: 'M12 3v12m0 0 4-4m-4 4-4-4M5 21h14',
    arrow: 'M5 12h14m-6-6 6 6-6 6',
    plus: 'M12 5v14M5 12h14',
    pin: 'M12 21s6-5.3 6-11a6 6 0 1 0-12 0c0 5.7 6 11 6 11Zm0-9a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z',
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d={paths[name]} /></svg>
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit' }).format(new Date(value))
}

function mapPosition(latitude: number | null, longitude: number | null) {
  if (latitude === null || longitude === null) return { left: '50%', top: '50%' }
  const left = Math.min(88, Math.max(12, ((longitude + 74.01) / 0.045) * 100))
  const top = Math.min(86, Math.max(14, (1 - (latitude - 40.72) / 0.04) * 100))
  return { left: `${left}%`, top: `${top}%` }
}

function App() {
  const [potholes, setPotholes] = useState<Pothole[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [query, setQuery] = useState('')
  const [activeNav, setActiveNav] = useState('Overview')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const selected = potholes.find((item) => item.id === selectedId) ?? potholes[0]
  const filtered = potholes.filter((item) => `${item.id} ${item.address}`.toLowerCase().includes(query.toLowerCase()))
  const severityAssessed = potholes.filter((item) => item.severity !== 'Unassessed').length
  const averageConfidence = potholes.length ? Math.round((potholes.reduce((sum, item) => sum + item.confidence, 0) / potholes.length) * 100) : 0
  const detectionsLast24Hours = potholes.filter((item) => Date.now() - new Date(item.timestamp).getTime() <= 24 * 60 * 60 * 1000).length
  const locationsCovered = new Set(potholes.filter((item) => item.latitude !== null && item.longitude !== null).map((item) => `${item.latitude},${item.longitude}`)).size
  const connectionLabel = loadError ? 'Backend offline' : loading ? 'Connecting to backend' : 'Backend connected'
  const connectionDetail = loadError ? 'Start the CivicAI API on port 8000' : loading ? 'Loading persisted detections' : 'Data source: CivicAI API'

  useEffect(() => {
    let active = true
    fetch('/api/potholes')
      .then((response) => {
        if (!response.ok) throw new Error(`Backend returned ${response.status}.`)
        return response.json() as Promise<Pothole[]>
      })
      .then((data) => {
        if (!active) return
        setPotholes(data)
        setSelectedId(data[0]?.id ?? '')
      })
      .catch((error: unknown) => {
        if (active) setLoadError(error instanceof Error ? error.message : 'Unable to load detections.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [])

  const report = useMemo(() => selected ? `CivicAI recorded a pothole detection candidate at ${selected.address}. Model confidence is ${Math.round(selected.confidence * 100)}%, processed ${formatTime(selected.timestamp)}. Physical severity, dimensions, and repair status have not been assessed by this system.` : '', [selected])

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark">C</div><div><strong>Civic<span>AI</span></strong><small>INFRASTRUCTURE INTELLIGENCE</small></div></div>
        <div className="workspace-label">WORKSPACE</div>
        <div className="workspace"><div className="workspace-avatar">CA</div><div><b>CivicAI Operations</b><small>Live backend workspace</small></div><span>⌄</span></div>
        <nav>
          {['Overview', 'Live map', 'Evidence gallery', 'Reports'].map((item, index) => <button key={item} className={activeNav === item ? 'nav-item active' : 'nav-item'} onClick={() => setActiveNav(item)}>{icon(['grid', 'map', 'image', 'chart'][index])}<span>{item}</span>{item === 'Live map' && potholes.length > 0 && <i>{potholes.length}</i>}</button>)}
        </nav>
        <div className="sidebar-bottom"><button className="nav-item" onClick={() => setActiveNav('Settings')}>{icon('settings')}<span>Settings</span></button><div className={`system-status ${loadError ? 'offline' : ''}`}><span className="pulse" /> {connectionLabel}<small>{connectionDetail}</small></div><div className="profile"><div className="profile-avatar">AI</div><div><b>System operator</b><small>Infrastructure intelligence</small></div><span>•••</span></div></div>
      </aside>
      <main className="main-content">
        <header className="topbar"><div className="breadcrumb"><span>Workspace</span><b>/</b><strong>{activeNav}</strong></div><div className="top-actions"><div className="search">{icon('search')}<input placeholder="Search detections..." value={query} onChange={(event) => setQuery(event.target.value)} /><kbd>⌘ K</kbd></div><button className="icon-button" aria-label="Notifications">{icon('bell')}<em /></button><div className={`live-pill ${loadError ? 'offline' : ''}`}><span /> {loadError ? 'API offline' : loading ? 'Connecting' : 'Live data'}</div></div></header>
        <section className="content">
          {loading && <div className="data-state">Loading detections from CivicAI backend…</div>}
          {!loading && loadError && <div className="data-state error">Unable to load real detections: {loadError}</div>}
          {!loading && !loadError && potholes.length === 0 && <div className="data-state">No pothole detections have been persisted yet.</div>}
          <div className="intro-row"><div><p className="eyebrow">CIVICAI OPERATIONS <span className="dot" /> LIVE DATABASE</p><h1>Infrastructure intelligence <span>✦</span></h1><p className="subheading">A live view of persisted pothole detections from the CivicAI backend.</p></div><div className="intro-actions"><button className="button primary" onClick={() => window.print()}>{icon('download')} Export report</button></div></div>
          <div className="stat-grid"><StatCard label="Total detections" value={potholes.length.toString()} delta="Persisted" note="in CivicAI database" iconName="pin" accent="mint" /><StatCard label="High priority" value={highPriority.toString().padStart(2, '0')} delta="Current records" note="confidence ≥ 90%" iconName="chart" accent="orange" /><StatCard label="Avg. confidence" value={`${averageConfidence}%`} delta="Database average" note="across detections" iconName="chart" accent="blue" /><StatCard label="GPS locations" value={locationsCovered.toString()} delta="Available coordinates" note="from persisted records" iconName="map" accent="purple" /></div>
          <div className="dashboard-grid">
            <section className="panel map-panel"><div className="panel-heading"><div><p className="eyebrow">GEO-SPATIAL OVERVIEW</p><h2>Detection activity</h2></div><button className="text-button" onClick={() => setActiveNav('Live map')}>View full map {icon('arrow')}</button></div><div className="map-wrap"><div className="map-grid" /><div className="road road-a" /><div className="road road-b" /><div className="road road-c" /><div className="road road-d" />{potholes.filter((item) => item.latitude !== null && item.longitude !== null).map((item) => <button key={item.id} className={`map-pin ${item.id === selectedId ? 'selected' : ''}`} style={mapPosition(item.latitude, item.longitude)} onClick={() => setSelectedId(item.id)} aria-label={`Select ${item.id}`}><span>{icon('pin')}</span></button>)}{locationsCovered === 0 && <div className="map-empty">No GPS coordinates in persisted detections.</div>}<div className="map-legend"><span><i className="legend-dot high" /> High priority</span><span><i className="legend-dot medium" /> Monitoring</span></div><div className="map-controls"><button>+</button><button>−</button><button>{icon('pin')}</button></div></div></section>
            <section className="panel activity-panel"><div className="panel-heading"><div><p className="eyebrow">LAST 24 HOURS</p><h2>Detection volume</h2></div><span className="data-source">Live database</span></div><div className="chart-summary"><strong>{detectionsLast24Hours}</strong><span>detections <b>persisted</b></span></div><div className="empty-chart">{detectionsLast24Hours === 0 ? 'No detections recorded in the last 24 hours.' : `${detectionsLast24Hours} detection${detectionsLast24Hours === 1 ? '' : 's'} recorded in the last 24 hours.`}</div></section>
          </div>
          <div className="lower-grid">
            <section className="panel gallery-panel"><div className="panel-heading"><div><p className="eyebrow">RECENT EVIDENCE</p><h2>Captured potholes <span className="count-badge">{filtered.length}</span></h2></div><button className="text-button" onClick={() => setActiveNav('Evidence gallery')}>View gallery {icon('arrow')}</button></div><div className="gallery-grid">{filtered.slice(0, 4).map((item) => <button className={`evidence-card ${item.id === selectedId ? 'selected' : ''}`} key={item.id} onClick={() => setSelectedId(item.id)}><div className="evidence-image"><img src={item.image_url} alt={`Evidence for ${item.id}`} /><span className={`confidence ${item.severity.toLowerCase()}`}>{Math.round(item.confidence * 100)}%</span><span className="image-expand">↗</span></div><div className="evidence-meta"><div><b>{item.id}</b><small>{formatTime(item.timestamp)} <span>•</span> {item.address}</small></div><span className={`severity ${item.severity.toLowerCase()}`}>{item.severity}</span></div></button>)}</div></section>
            <section className="panel detail-panel"><div className="panel-heading"><div><p className="eyebrow">SELECTED INCIDENT</p><h2>{selected?.id ?? 'No selection'}</h2></div><button className="more-button">•••</button></div>{selected && <><div className="detail-image"><img src={selected.image_url} alt="" /><span className="verified-tag">AI detected</span></div><div className="detail-fields"><div><small>LOCATION</small><b>{selected.address}</b><span>{selected.latitude !== null && selected.longitude !== null ? `${selected.latitude.toFixed(4)}° N, ${Math.abs(selected.longitude).toFixed(4)}° W` : 'GPS coordinates unavailable'}</span></div><div><small>CAPTURED</small><b>{formatTime(selected.timestamp)}</b><span>Persisted detection record</span></div><div><small>MODEL CONFIDENCE</small><b>{Math.round(selected.confidence * 100)}% <span className={`severity ${selected.severity.toLowerCase()}`}>{selected.severity}</span></b><span>Confidence is not severity</span></div></div><div className="report-box"><small>AUTO-GENERATED INCIDENT REPORT</small><p>{report}</p></div><button className="button primary full" onClick={() => setActiveNav('Reports')}>Open full incident report {icon('arrow')}</button></>}</section>
          </div>
        </section>
      </main>
    </div>
  )
}

function StatCard({ label, value, delta, note, iconName, accent }: { label: string; value: string; delta: string; note: string; iconName: string; accent: string }) {
  return <div className={`stat-card ${accent}`}><div className="stat-top"><span>{label}</span><div className="stat-icon">{icon(iconName)}</div></div><div className="stat-value">{value}</div><div className="stat-foot"><b>{delta}</b><span>{note}</span></div></div>
}

export default App
