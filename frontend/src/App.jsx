import { useState, useEffect, useCallback } from 'react'

const API = '/api'

const VIEWS = [
  { key: 'home', icon: '🏠', label: 'Wszystkie' },
  { key: 'telegram', icon: '✈️', label: 'Telegram' },
  { key: 'x', icon: '𝕏', label: 'X' },
  { key: 'facebook', icon: '📘', label: 'Facebook' },
  { key: 'history', icon: '📋', label: 'Historia' },
  { key: 'scheduled', icon: '🕐', label: 'Zaplanowane' },
  { key: 'calendar', icon: '📅', label: 'Kalendarz' },
  { key: 'rss', icon: '📡', label: 'RSS' },
  { key: 'templates', icon: '📄', label: 'Szablony' },
  { key: 'creator', icon: '✏️', label: 'Kreator' },
]

const TONE_BADGE = {
  escalation: { label: 'Eskalacja', cls: 'badgeToneEscalation' },
  tension: { label: 'Napięcie', cls: 'badgeToneTension' },
  diplomacy: { label: 'Dyplomacja', cls: 'badgeToneDiplomacy' },
}

function usePostList(refreshMs = 5000) {
  const [list, setList] = useState({ new: [], in_progress: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const refresh = useCallback(() => {
    fetch(API + '/posts')
      .then((r) => r.json())
      .then(setList)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])
  useEffect(() => {
    refresh()
    const id = setInterval(refresh, refreshMs)
    return () => clearInterval(id)
  }, [refresh, refreshMs])
  return { list, loading, error, refresh }
}

function Sidebar({ view, onView }) {
  return (
    <aside className="sidebar">
      {VIEWS.map(({ key, icon, label }) => (
        <button
          key={key}
          className={view === key ? 'active' : ''}
          onClick={() => onView(key)}
          title={label}
        >
          {icon}
        </button>
      ))}
    </aside>
  )
}

function ToneBadge({ tone }) {
  const info = TONE_BADGE[tone]
  if (!info) return null
  return <span className={`toneBadge ${info.cls}`}>{info.label}</span>
}

function TagList({ tags }) {
  if (!tags || tags.length === 0) return null
  return <span className="tagList">{tags.map((t) => <span key={t} className="tag">{t}</span>)}</span>
}

function PostList({ list, loading, error, view, onSelect, onAdoptFromList, refreshList, selectedIds, setSelectedIds }) {
  if (loading && (list.new?.length === 0) && (list.in_progress?.length === 0))
    return <div className="loading">Ładowanie…</div>
  if (error) return <div className="error">{error}</div>

  const newPosts = list.new || []
  let inProgress = list.in_progress || []
  if (view !== 'home') {
    const platform = view
    inProgress = inProgress.filter((p) => p.platform === platform)
  }

  const showNew = view === 'home' && newPosts.length > 0
  const showInProgress = inProgress.length > 0

  if (!showNew && !showInProgress)
    return (
      <div className="empty">
        {view === 'home'
          ? 'Brak postów. Nowe pojawią się po przekazaniu do bota lub z kanałów.'
          : `Brak postów w sekcji ${VIEWS.find((v) => v.key === view)?.label || view}.`}
      </div>
    )

  const handleAdopt = (e, postId, platform) => {
    e.stopPropagation()
    onAdoptFromList(postId, platform)
  }

  const toggleSelect = (e, id) => {
    e.stopPropagation()
    setSelectedIds((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => {
    const allIds = newPosts.map((p) => p.id)
    const allSelected = allIds.every((id) => selectedIds.has(id))
    if (allSelected) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(allIds))
    }
  }

  return (
    <div className="postList">
      {showNew && (
        <>
          <div className="sectionHeader">
            <h2>Nowe</h2>
            {newPosts.length > 1 && (
              <label className="selectAll" onClick={toggleSelectAll}>
                <input type="checkbox" checked={newPosts.every((p) => selectedIds.has(p.id))} readOnly /> Zaznacz wszystkie
              </label>
            )}
          </div>
          {newPosts.map((p) => (
            <div key={'new-' + p.id} className="postCard newCard" onClick={() => onSelect(p.id)}>
              <div className="cardContent">
                <div className="cardCheck" onClick={(e) => toggleSelect(e, p.id)}>
                  <input type="checkbox" checked={selectedIds.has(p.id)} readOnly />
                </div>
                <div className="cardInner">
                  {p.has_media && (
                    <div className="cardMedia">
                      <img
                        src={API + '/posts/' + encodeURIComponent(p.id) + '/media/0'}
                        alt=""
                        onError={(e) => { e.target.style.display = 'none' }}
                      />
                    </div>
                  )}
                  <div className="cardBody">
                    <div className="source">
                      {p.source}
                      <ToneBadge tone={p.tone} />
                    </div>
                    <TagList tags={p.tags} />
                    <div className="preview fullText">{p.original_text || '—'}</div>
                    <div className="meta">{p.has_media ? '📎 ' : ''}ID: {p.id}</div>
                    <div className="quickAdopt" onClick={(e) => e.stopPropagation()}>
                      <span className="quickLabel">Przekaż:</span>
                      <button type="button" className="btnT" onClick={(e) => handleAdopt(e, p.id, 'telegram')} title="Adoptuj → Telegram">→ T</button>
                      <button type="button" className="btnX" onClick={(e) => handleAdopt(e, p.id, 'x')} title="Adoptuj → X">→ X</button>
                      <button type="button" className="btnF" onClick={(e) => handleAdopt(e, p.id, 'facebook')} title="Adoptuj → Facebook">→ F</button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </>
      )}
      {showInProgress && (
        <>
          <h2>{view === 'home' ? 'W trakcie' : VIEWS.find((v) => v.key === view)?.label}</h2>
          {inProgress.map((p) => {
            const hasDraft = [p.status_telegram, p.status_x, p.status_facebook].some((s) => s === 'draft')
            const statusClass = hasDraft ? 'status-draft' : 'status-empty'
            return (
              <div
                key={p.id}
                className={`postCard ${statusClass}`}
                onClick={() => onSelect(p.id)}
              >
                <div className="cardContent">
                  {p.has_media && p.media_count > 0 && (
                    <div className="cardMedia">
                      <img
                        src={API + '/posts/' + encodeURIComponent(p.id) + '/media/0'}
                        alt=""
                        onError={(e) => { e.target.style.display = 'none' }}
                      />
                    </div>
                  )}
                  <div className="cardBody">
                    <div className="source">
                      {p.source}
                      <ToneBadge tone={p.tone} />
                    </div>
                    <TagList tags={p.tags} />
                    <div className="preview fullText">
                      {p.text_telegram || p.text_x || p.text_facebook || p.original_text || '—'}
                    </div>
                    <div className="meta">
                      {p.platform} · ID: {p.id}
                      {hasDraft && <span className="badgeDraft"> zapisane</span>}
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </>
      )}
    </div>
  )
}

const PLATFORMS = [
  { key: 'telegram', label: 'Telegram' },
  { key: 'x', label: 'X' },
  { key: 'facebook', label: 'Facebook' },
]

function PostDetail({ postId, onBack, refreshList }) {
  const [post, setPost] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('telegram')
  const [saving, setSaving] = useState(false)

  const loadPost = useCallback(() => {
    if (!postId) return
    setLoading(true)
    fetch(API + '/posts/' + encodeURIComponent(postId))
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('Not found'))))
      .then(setPost)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [postId])

  useEffect(() => loadPost(), [loadPost])

  const textFor = (platform) => {
    if (!post) return ''
    return post['text_' + platform] || post.text || ''
  }
  const setTextFor = (platform, value) => {
    setPost((p) => ({ ...p, ['text_' + platform]: value }))
  }

  const displayText = post?.in_progress ? textFor(tab) : (post?.original_text || '')
  const mediaUrl = post?.has_media ? API + '/posts/' + encodeURIComponent(postId) + '/media/0' : null

  const copyText = () => {
    const toCopy = post?.in_progress ? textFor(tab) : (post?.original_text || '')
    navigator.clipboard.writeText(toCopy).then(() => alert('Skopiowano'))
  }

  const downloadMedia = () => {
    window.open(API + '/posts/' + encodeURIComponent(postId) + '/media/0', '_blank')
  }

  const adopt = (platform) => {
    setSaving(true)
    fetch(API + '/posts/' + encodeURIComponent(postId) + '/adopt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platform }),
    })
      .then((r) => r.json())
      .then((d) => {
        refreshList()
        if (d.id) onBack(d.id)
      })
      .catch((e) => alert(e.message))
      .finally(() => setSaving(false))
  }

  const generate = (platform) => {
    setSaving(true)
    fetch(API + '/posts/' + encodeURIComponent(postId) + '/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platform }),
    })
      .then((r) => r.json())
      .then((d) => setPost((p) => ({ ...p, ['text_' + platform]: d.text })))
      .catch((e) => alert(e.message))
      .finally(() => setSaving(false))
  }

  const saveText = (platform) => {
    const text = textFor(platform)
    setSaving(true)
    fetch(API + '/posts/' + encodeURIComponent(postId) + '/text', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platform, text }),
    })
      .then(() => loadPost())
      .catch((e) => alert(e.message))
      .finally(() => setSaving(false))
  }

  const [showSchedule, setShowSchedule] = useState(false)
  const [scheduleDate, setScheduleDate] = useState('')
  const [bestHours, setBestHours] = useState([])
  const [tplList, setTplList] = useState([])

  useEffect(() => {
    fetch(API + '/analytics/best-times').then((r) => r.json()).then((d) => setBestHours(d.best_hours || [])).catch(() => {})
    fetch(API + '/templates').then((r) => r.json()).then((d) => setTplList(d.templates || [])).catch(() => {})
  }, [])

  const publish = (platform) => {
    setSaving(true)
    fetch(API + '/posts/' + encodeURIComponent(postId) + '/publish/' + platform, { method: 'POST' })
      .then((r) => r.json())
      .then(() => alert('Opublikowano'))
      .catch((e) => alert(e.message))
      .finally(() => setSaving(false))
  }

  const schedule = (platform) => {
    if (!scheduleDate) { alert('Wybierz datę i godzinę'); return }
    const publishAt = scheduleDate.replace('T', 'T') + ':00'
    setSaving(true)
    fetch(API + '/posts/' + encodeURIComponent(postId) + '/schedule', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platform, publish_at: publishAt }),
    })
      .then((r) => r.json())
      .then(() => { alert('Zaplanowano'); setShowSchedule(false) })
      .catch((e) => alert(e.message))
      .finally(() => setSaving(false))
  }

  const rephrase = (style) => {
    setSaving(true)
    fetch(API + '/posts/' + encodeURIComponent(postId) + '/rephrase', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ style }),
    })
      .then((r) => r.json())
      .then((d) => setPost((p) => ({ ...p, text: d.text, ['text_' + tab]: d.text })))
      .catch((e) => alert(e.message))
      .finally(() => setSaving(false))
  }

  const reject = () => {
    if (!confirm('Odrzucić ten post?')) return
    setSaving(true)
    fetch(API + '/posts/' + encodeURIComponent(postId) + '/reject', { method: 'POST' })
      .then(() => {
        refreshList()
        onBack(null)
      })
      .finally(() => setSaving(false))
  }

  if (loading) return <div className="loading">Ładowanie posta…</div>
  if (error) return <div className="error">{error}</div>
  if (!post) return null

  const isNew = !post.in_progress

  const setApprovalStatus = (status) => {
    setSaving(true)
    fetch(API + '/posts/' + encodeURIComponent(postId) + '/status', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    })
      .then((r) => r.json())
      .then(() => setPost((p) => ({ ...p, approval_status: status })))
      .catch((e) => alert(e.message))
      .finally(() => setSaving(false))
  }

  const detectTone = () => {
    setSaving(true)
    fetch(API + '/posts/' + encodeURIComponent(postId) + '/detect-tone', { method: 'POST' })
      .then((r) => r.json())
      .then((d) => setPost((p) => ({ ...p, tone: d.tone })))
      .catch((e) => alert(e.message))
      .finally(() => setSaving(false))
  }

  return (
    <div className="postDetail">
      <div className="header">
        <h1>
          {post.source}
          <ToneBadge tone={post.tone} />
          {!post.tone && <button className="btnSmall" onClick={detectTone} disabled={saving}>Wykryj ton</button>}
        </h1>
        <button onClick={() => onBack(null)}>← Lista</button>
      </div>
      {post.tags && post.tags.length > 0 && <TagList tags={post.tags} />}

      {/* Approval status */}
      {post.in_progress && (
        <div className="approvalBar">
          <span className="approvalLabel">Status:</span>
          {['draft', 'ready_for_review', 'approved'].map((s) => (
            <button
              key={s}
              className={`approvalBtn ${post.approval_status === s ? 'active' : ''}`}
              onClick={() => setApprovalStatus(s)}
              disabled={saving}
            >
              {s === 'draft' ? 'Szkic' : s === 'ready_for_review' ? 'Do przeglądu' : 'Zatwierdzony'}
            </button>
          ))}
        </div>
      )}

      {/* Podgląd jak na Telegramie: medium + text */}
      <section className="previewBlock">
        <h3>Podgląd</h3>
        <div className="telegramPreview">
          {post.has_media && mediaUrl && (
            <div className="previewMedia">
              <img src={mediaUrl} alt="" onError={(e) => { e.target.style.display = 'none' }} />
            </div>
          )}
          <div className="previewText">{displayText || '—'}</div>
        </div>
      </section>

      {/* Platform previews */}
      {post.in_progress && (
        <section className="platformPreviews">
          <h3>Podgląd per platforma</h3>
          <div className="previewGrid">
            <div className="previewCard previewTelegram">
              <div className="previewCardHeader">Telegram</div>
              <div className="previewCardBody">{post.text_telegram || '—'}</div>
            </div>
            <div className="previewCard previewX">
              <div className="previewCardHeader">
                X <span className={`charCount ${(post.text_x || '').length > 280 ? 'over' : ''}`}>{(post.text_x || '').length}/280</span>
              </div>
              <div className="previewCardBody">{post.text_x || '—'}</div>
            </div>
            <div className="previewCard previewFacebook">
              <div className="previewCardHeader">Facebook</div>
              <div className="previewCardBody">{post.text_facebook || '—'}</div>
            </div>
          </div>
        </section>
      )}

      {/* Oryginał (pełny tekst) */}
      <section className="originalBlock">
        <h3>Oryginał</h3>
        <div className="quote fullText">{post.original_text || '—'}</div>
      </section>

      {post.has_media && (
        <div className="mediaWrap">
          <div className="mediaOverlay">
            <button onClick={copyText}>Copy</button>
            <button onClick={downloadMedia}>Download</button>
          </div>
          {mediaUrl && (
            <img src={mediaUrl} alt="" onError={(e) => { e.target.style.display = 'none' }} />
          )}
        </div>
      )}

      {isNew ? (
        <div className="actions">
          <span className="actionLabel">Przekaż do:</span>
          {PLATFORMS.map(({ key, label }) => (
            <button key={key} className="primary" onClick={() => adopt(key)} disabled={saving}>
              → {label}
            </button>
          ))}
          <button className="danger" onClick={reject} disabled={saving}>Odrzuć</button>
        </div>
      ) : (
        <>
          <div className="tabs">
            {PLATFORMS.map(({ key, label }) => (
              <button
                key={key}
                className={tab === key ? 'active' : ''}
                onClick={() => setTab(key)}
              >
                {label}
              </button>
            ))}
          </div>
          {tplList.length > 0 && (
            <div className="templateDropdown">
              <select defaultValue="" onChange={(e) => {
                const tpl = tplList.find((t) => t.id === e.target.value)
                if (tpl) setTextFor(tab, tpl.body)
                e.target.value = ''
              }}>
                <option value="" disabled>Zastosuj szablon...</option>
                {tplList.filter((t) => !t.platform || t.platform === tab).map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>
          )}
          <textarea
            className="textArea"
            value={textFor(tab)}
            onChange={(e) => setTextFor(tab, e.target.value)}
            placeholder={tab === 'telegram' ? 'Tekst dla Telegrama' : tab === 'x' ? 'Tweet' : 'Post na FB'}
          />
          <div className="actions">
            {!textFor(tab) && (
              <button onClick={() => generate(tab)} disabled={saving}>Generuj ({tab})</button>
            )}
            <button onClick={() => saveText(tab)} disabled={saving}>Zapisz</button>
            <button className="primary" onClick={() => publish(tab)} disabled={saving}>Publikuj {tab}</button>
            <button onClick={() => setShowSchedule(!showSchedule)} disabled={saving}>Zaplanuj</button>
            <button onClick={() => rephrase('longer')} disabled={saving}>Wydłuż</button>
            <button onClick={() => rephrase('shorter')} disabled={saving}>Skróć</button>
            <button onClick={() => rephrase('retry')} disabled={saving}>Retry</button>
            <button className="danger" onClick={reject} disabled={saving}>Odrzuć</button>
          </div>
          {showSchedule && (
            <div className="scheduleModal">
              <label>Data i godzina publikacji:</label>
              <input type="datetime-local" value={scheduleDate} onChange={(e) => setScheduleDate(e.target.value)} />
              <button className="primary" onClick={() => schedule(tab)} disabled={saving || !scheduleDate}>Zaplanuj na {tab}</button>
              <button onClick={() => setShowSchedule(false)}>Anuluj</button>
              {bestHours.length > 0 && (
                <div className="bestTimeHint">Sugerowane godziny: {bestHours.map((h) => `${String(h).padStart(2, '0')}:00`).join(', ')}</div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function ScheduledView() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    fetch(API + '/scheduled')
      .then((r) => r.json())
      .then((d) => setItems(d.items || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => load(), [load])

  const cancel = (schedId) => {
    if (!confirm('Anulować zaplanowaną publikację?')) return
    fetch(API + '/scheduled/' + encodeURIComponent(schedId), { method: 'DELETE' })
      .then(() => load())
      .catch((e) => alert(e.message))
  }

  return (
    <div className="historyView">
      <h2>Zaplanowane publikacje</h2>
      {loading ? (
        <div className="loading">Ładowanie…</div>
      ) : items.length === 0 ? (
        <div className="empty">Brak zaplanowanych publikacji.</div>
      ) : (
        <table className="historyTable">
          <thead>
            <tr>
              <th>Data publikacji</th>
              <th>Platforma</th>
              <th>Post ID</th>
              <th>Utworzono</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.id}>
                <td className="historyDate">{(r.publish_at || '').replace('T', ' ').slice(0, 16)}</td>
                <td className="historyPlatform">{r.platform}</td>
                <td>{r.post_id}</td>
                <td className="historyDate">{(r.created_at || '').replace('T', ' ').slice(0, 16)}</td>
                <td><button className="danger btnSmall" onClick={() => cancel(r.id)}>Anuluj</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function BulkActionBar({ selectedIds, setSelectedIds, refreshList }) {
  const [loading, setLoading] = useState(false)

  if (selectedIds.size === 0) return null

  const bulkAdopt = (platform) => {
    setLoading(true)
    fetch(API + '/posts/bulk-adopt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: Array.from(selectedIds), platform }),
    })
      .then((r) => r.json())
      .then(() => { setSelectedIds(new Set()); refreshList() })
      .catch((e) => alert(e.message))
      .finally(() => setLoading(false))
  }

  const bulkReject = () => {
    if (!confirm(`Odrzucić ${selectedIds.size} postów?`)) return
    setLoading(true)
    fetch(API + '/posts/bulk-reject', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: Array.from(selectedIds) }),
    })
      .then((r) => r.json())
      .then(() => { setSelectedIds(new Set()); refreshList() })
      .catch((e) => alert(e.message))
      .finally(() => setLoading(false))
  }

  return (
    <div className="bulkBar">
      <span>Zaznaczono: {selectedIds.size}</span>
      <button className="btnT" onClick={() => bulkAdopt('telegram')} disabled={loading}>Adoptuj → T</button>
      <button className="btnX" onClick={() => bulkAdopt('x')} disabled={loading}>Adoptuj → X</button>
      <button className="btnF" onClick={() => bulkAdopt('facebook')} disabled={loading}>Adoptuj → F</button>
      <button className="danger" onClick={bulkReject} disabled={loading}>Odrzuć</button>
      <button onClick={() => setSelectedIds(new Set())}>Anuluj</button>
    </div>
  )
}

function HistoryView() {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')
  const [platform, setPlatform] = useState('')
  const [offset, setOffset] = useState(0)
  const limit = 50

  const load = useCallback(() => {
    setLoading(true)
    const params = new URLSearchParams({ limit, offset })
    if (platform) params.set('platform', platform)
    if (q) params.set('q', q)
    fetch(API + '/published?' + params)
      .then((r) => r.json())
      .then((d) => { setItems(d.items || []); setTotal(d.total || 0) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [q, platform, offset])

  useEffect(() => load(), [load])

  const recycle = (pubId) => {
    fetch(API + '/published/' + encodeURIComponent(pubId) + '/recycle', { method: 'POST' })
      .then((r) => r.json())
      .then((d) => alert('Wznowiono jako ' + d.id))
      .catch((e) => alert(e.message))
  }

  const search = (e) => {
    e.preventDefault()
    setOffset(0)
    load()
  }

  return (
    <div className="historyView">
      <h2>Historia publikacji</h2>
      <form className="historyFilters" onSubmit={search}>
        <input type="text" placeholder="Szukaj..." value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={platform} onChange={(e) => { setPlatform(e.target.value); setOffset(0) }}>
          <option value="">Wszystkie</option>
          <option value="telegram">Telegram</option>
          <option value="facebook">Facebook</option>
          <option value="x">X</option>
        </select>
        <button type="submit">Szukaj</button>
      </form>
      {loading ? (
        <div className="loading">Ładowanie…</div>
      ) : items.length === 0 ? (
        <div className="empty">Brak opublikowanych postów.</div>
      ) : (
        <>
          <div className="historyStats">Znaleziono: {total}</div>
          <table className="historyTable">
            <thead>
              <tr>
                <th>Data</th>
                <th>Platforma</th>
                <th>Źródło</th>
                <th>Tekst</th>
                <th>Tagi</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id}>
                  <td className="historyDate">{(r.published_at || '').replace('T', ' ').slice(0, 16)}</td>
                  <td className="historyPlatform">{r.platform}</td>
                  <td className="historySource">{r.source}</td>
                  <td className="historyText">{(r.text || '').slice(0, 120)}{(r.text || '').length > 120 ? '…' : ''}</td>
                  <td><TagList tags={r.tags} /></td>
                  <td><button className="btnSmall" onClick={() => recycle(r.id)}>Wznów</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="historyPagination">
            {offset > 0 && <button onClick={() => setOffset(Math.max(0, offset - limit))}>← Poprzednia</button>}
            {offset + limit < total && <button onClick={() => setOffset(offset + limit)}>Następna →</button>}
          </div>
        </>
      )}
    </div>
  )
}

function CalendarView() {
  const today = new Date()
  const [year, setYear] = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth() + 1)
  const [days, setDays] = useState({})
  const [loading, setLoading] = useState(true)

  const monthStr = `${year}-${String(month).padStart(2, '0')}`

  const load = useCallback(() => {
    setLoading(true)
    fetch(API + '/calendar?month=' + monthStr)
      .then((r) => r.json())
      .then((d) => setDays(d.days || {}))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [monthStr])

  useEffect(() => load(), [load])

  const prev = () => {
    if (month === 1) { setYear(year - 1); setMonth(12) }
    else setMonth(month - 1)
  }
  const next = () => {
    if (month === 12) { setYear(year + 1); setMonth(1) }
    else setMonth(month + 1)
  }

  const daysInMonth = new Date(year, month, 0).getDate()
  const firstDow = (new Date(year, month - 1, 1).getDay() + 6) % 7 // Monday=0
  const todayStr = today.toISOString().slice(0, 10)
  const dayNames = ['Pn', 'Wt', 'Sr', 'Cz', 'Pt', 'Sb', 'Nd']

  return (
    <div className="calendarView">
      <h2>Kalendarz</h2>
      <div className="calendarNav">
        <button onClick={prev}>&larr;</button>
        <span>{monthStr}</span>
        <button onClick={next}>&rarr;</button>
      </div>
      {loading ? <div className="loading">Ladowanie...</div> : (
        <div className="calendarGrid">
          {dayNames.map((d) => <div key={d} className="calendarDayHeader">{d}</div>)}
          {Array.from({ length: firstDow }).map((_, i) => <div key={'e' + i} className="calendarDay empty" />)}
          {Array.from({ length: daysInMonth }).map((_, i) => {
            const day = i + 1
            const dayKey = `${monthStr}-${String(day).padStart(2, '0')}`
            const entries = days[dayKey] || []
            const isToday = dayKey === todayStr
            return (
              <div key={dayKey} className={`calendarDay${isToday ? ' today' : ''}`}>
                <div className="calendarDayNum">{day}</div>
                {entries.slice(0, 3).map((e, j) => (
                  <div key={j} className={`calendarEntry ${e.type}`}>
                    {e.time} {e.platform} {e.text ? e.text.slice(0, 20) : ''}
                  </div>
                ))}
                {entries.length > 3 && <div className="calendarEntry">+{entries.length - 3}</div>}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function RssView() {
  const [feeds, setFeeds] = useState([])
  const [loading, setLoading] = useState(true)
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    fetch(API + '/rss')
      .then((r) => r.json())
      .then((d) => setFeeds(d.feeds || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => load(), [load])

  const addFeed = (e) => {
    e.preventDefault()
    if (!url.trim()) return
    fetch(API + '/rss', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: url.trim(), name: name.trim() }),
    })
      .then((r) => { if (!r.ok) throw new Error('Blad'); return r.json() })
      .then(() => { setUrl(''); setName(''); load() })
      .catch((e) => alert(e.message))
  }

  const removeFeed = (id) => {
    if (!confirm('Usunac ten feed?')) return
    fetch(API + '/rss/' + encodeURIComponent(id), { method: 'DELETE' })
      .then(() => load())
  }

  const toggleFeed = (id, active) => {
    fetch(API + '/rss/' + encodeURIComponent(id) + '/toggle', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ active }),
    }).then(() => load())
  }

  return (
    <div className="rssView">
      <h2>Feedy RSS</h2>
      <form className="rssAddForm" onSubmit={addFeed}>
        <input className="rssUrl" type="text" placeholder="URL feedu RSS..." value={url} onChange={(e) => setUrl(e.target.value)} />
        <input className="rssName" type="text" placeholder="Nazwa (opcj.)" value={name} onChange={(e) => setName(e.target.value)} />
        <button type="submit">Dodaj</button>
      </form>
      {loading ? <div className="loading">Ladowanie...</div> : feeds.length === 0 ? (
        <div className="empty">Brak feedow RSS.</div>
      ) : (
        <div className="rssList">
          {feeds.map((f) => (
            <div key={f.id} className="rssItem">
              <div className="rssInfo">
                <div className="rssName">{f.name}</div>
                <div className="rssUrlText">{f.url}</div>
                <span className={f.active ? 'rssActive' : 'rssInactive'}>{f.active ? 'Aktywny' : 'Wstrzymany'}</span>
              </div>
              <button className="btnSmall" onClick={() => toggleFeed(f.id, !f.active)}>{f.active ? 'Wstrzymaj' : 'Wznow'}</button>
              <button className="btnSmall danger" onClick={() => removeFeed(f.id)}>Usun</button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function TemplatesView() {
  const [templates, setTemplates] = useState([])
  const [loading, setLoading] = useState(true)
  const [tplName, setTplName] = useState('')
  const [tplBody, setTplBody] = useState('')
  const [tplPlatform, setTplPlatform] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    fetch(API + '/templates')
      .then((r) => r.json())
      .then((d) => setTemplates(d.templates || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => load(), [load])

  const addTemplate = (e) => {
    e.preventDefault()
    if (!tplName.trim() || !tplBody.trim()) return
    fetch(API + '/templates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: tplName.trim(), body: tplBody.trim(), platform: tplPlatform }),
    })
      .then((r) => r.json())
      .then(() => { setTplName(''); setTplBody(''); setTplPlatform(''); load() })
      .catch((e) => alert(e.message))
  }

  const deleteTemplate = (id) => {
    if (!confirm('Usunac szablon?')) return
    fetch(API + '/templates/' + encodeURIComponent(id), { method: 'DELETE' })
      .then(() => load())
  }

  return (
    <div className="templatesView">
      <h2>Szablony</h2>
      <form className="templateForm" onSubmit={addTemplate}>
        <input type="text" placeholder="Nazwa szablonu" value={tplName} onChange={(e) => setTplName(e.target.value)} />
        <select value={tplPlatform} onChange={(e) => setTplPlatform(e.target.value)}>
          <option value="">Wszystkie platformy</option>
          <option value="telegram">Telegram</option>
          <option value="x">X</option>
          <option value="facebook">Facebook</option>
        </select>
        <textarea placeholder="Tresc szablonu..." value={tplBody} onChange={(e) => setTplBody(e.target.value)} />
        <button type="submit">Dodaj szablon</button>
      </form>
      {loading ? <div className="loading">Ladowanie...</div> : templates.length === 0 ? (
        <div className="empty">Brak szablonow.</div>
      ) : (
        <div className="templateList">
          {templates.map((t) => (
            <div key={t.id} className="templateItem">
              <div className="tplInfo">
                <div className="tplName">{t.name} {t.platform && <span className="tplPlatform">({t.platform})</span>}</div>
                <div className="tplBody">{t.body}</div>
              </div>
              <button className="btnSmall danger" onClick={() => deleteTemplate(t.id)}>Usun</button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function CreatorView({ onCreated }) {
  // Phases: input → scraped → generating → done
  const [phase, setPhase] = useState('input')
  const [url, setUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Scraped / uploaded data
  const [scrapedText, setScrapedText] = useState('')
  const [scrapedTitle, setScrapedTitle] = useState('')
  const [contextScore, setContextScore] = useState(10)
  const [mediaItems, setMediaItems] = useState([]) // [{url, filename, path, selected}]
  const [selectedMedia, setSelectedMedia] = useState(new Set())

  // Upload / paste state
  const [uploadedFiles, setUploadedFiles] = useState([]) // [{path, filename, description}]
  const [mediaAnalysis, setMediaAnalysis] = useState(null)
  const [extraContext, setExtraContext] = useState('')

  // Generation
  const [platforms, setPlatforms] = useState({ telegram: true, x: true, facebook: true })
  const [result, setResult] = useState(null)

  const scrapeUrl = async () => {
    if (!url.trim()) return
    setLoading(true)
    setError(null)
    try {
      const r = await fetch(API + '/creator/scrape-url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url.trim() }),
      })
      if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Blad') }
      const data = await r.json()
      setScrapedText(data.text || '')
      setScrapedTitle(data.title || '')
      setContextScore(data.context_score || 5)

      // Download media
      if (data.media_urls && data.media_urls.length > 0) {
        const dlResp = await fetch(API + '/creator/download-media', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ urls: data.media_urls }),
        })
        const dlData = await dlResp.json()
        const items = (dlData.media || []).map((m, i) => ({ ...m, id: i, selected: true }))
        setMediaItems(items)
        setSelectedMedia(new Set(items.map((m) => m.id)))
      }
      setPhase('scraped')
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleFileUpload = async (files) => {
    setLoading(true)
    setError(null)
    try {
      const uploaded = []
      for (const file of files) {
        const form = new FormData()
        form.append('file', file)
        const r = await fetch(API + '/creator/upload', { method: 'POST', body: form })
        if (!r.ok) throw new Error('Upload failed')
        const data = await r.json()
        uploaded.push({ ...data, originalName: file.name })
      }
      setUploadedFiles((prev) => [...prev, ...uploaded])

      // Auto-analyze first uploaded image
      if (uploaded.length > 0) {
        const first = uploaded[0]
        const ext = (first.filename || '').split('.').pop().toLowerCase()
        if (['jpg', 'jpeg', 'png', 'webp', 'gif'].includes(ext)) {
          const ar = await fetch(API + '/creator/analyze-media', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: first.path, context: extraContext }),
          })
          const analysis = await ar.json()
          setMediaAnalysis(analysis)
          setContextScore(analysis.context_score || 5)
          if (analysis.description) {
            setScrapedText(analysis.description)
          }
          setPhase('scraped')
        } else {
          setPhase('scraped')
        }
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const reanalyzeWithContext = async () => {
    if (uploadedFiles.length === 0) return
    setLoading(true)
    try {
      const ar = await fetch(API + '/creator/analyze-media', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: uploadedFiles[0].path, context: extraContext }),
      })
      const analysis = await ar.json()
      setMediaAnalysis(analysis)
      setContextScore(analysis.context_score || 5)
      if (analysis.description) setScrapedText(analysis.description)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handlePaste = (e) => {
    const items = e.clipboardData?.items
    if (!items) return
    const files = []
    for (const item of items) {
      if (item.kind === 'file') {
        const file = item.getAsFile()
        if (file) files.push(file)
      }
    }
    if (files.length > 0) {
      e.preventDefault()
      handleFileUpload(files)
    }
  }

  const handleDrop = (e) => {
    e.preventDefault()
    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) handleFileUpload(files)
  }

  const generate = async () => {
    const selectedPlatforms = Object.entries(platforms).filter(([, v]) => v).map(([k]) => k)
    if (selectedPlatforms.length === 0) { setError('Wybierz co najmniej jedna platforme'); return }
    if (!scrapedText.trim()) { setError('Brak tekstu do generowania'); return }

    // Collect media paths
    const mediaPaths = []
    for (const item of mediaItems) {
      if (selectedMedia.has(item.id) && item.path) mediaPaths.push(item.path)
    }
    for (const f of uploadedFiles) {
      mediaPaths.push(f.path)
    }

    setLoading(true)
    setError(null)
    try {
      const r = await fetch(API + '/creator/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: scrapedText,
          source: scrapedTitle || url || 'creator',
          platforms: selectedPlatforms,
          media_paths: mediaPaths,
        }),
      })
      if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Blad') }
      const data = await r.json()
      setResult(data)
      setPhase('done')
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const reset = () => {
    setPhase('input')
    setUrl('')
    setScrapedText('')
    setScrapedTitle('')
    setContextScore(10)
    setMediaItems([])
    setSelectedMedia(new Set())
    setUploadedFiles([])
    setMediaAnalysis(null)
    setExtraContext('')
    setResult(null)
    setError(null)
  }

  const toggleMedia = (id) => {
    setSelectedMedia((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  return (
    <div className="creatorView" onPaste={handlePaste}>
      <h2>Kreator posta</h2>
      {error && <div className="creatorError">{error}</div>}

      {phase === 'input' && (
        <>
          <div className="creatorSection">
            <h3>Wklej link</h3>
            <form className="creatorUrlForm" onSubmit={(e) => { e.preventDefault(); scrapeUrl() }}>
              <input
                type="text"
                placeholder="https://..."
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                className="creatorUrlInput"
              />
              <button type="submit" disabled={loading || !url.trim()} className="creatorBtn primary">
                {loading ? 'Czytam...' : 'Czytaj'}
              </button>
            </form>
          </div>

          <div className="creatorDivider">lub</div>

          <div className="creatorSection">
            <h3>Wklej / przeciagnij media</h3>
            <div
              className="creatorDropzone"
              onDragOver={(e) => e.preventDefault()}
              onDrop={handleDrop}
            >
              <div className="dropzoneText">
                {loading ? 'Przesylam...' : 'Ctrl+V aby wkleic screenshot, lub przeciagnij plik tutaj'}
              </div>
              <input
                type="file"
                multiple
                accept="image/*,video/*"
                onChange={(e) => handleFileUpload(Array.from(e.target.files))}
                className="dropzoneInput"
              />
            </div>

            {uploadedFiles.length > 0 && (
              <div className="creatorUploaded">
                {uploadedFiles.map((f, i) => (
                  <div key={i} className="uploadedItem">
                    <img
                      src={API + '/creator/media/' + encodeURIComponent(f.filename)}
                      alt=""
                      onError={(e) => { e.target.style.display = 'none' }}
                    />
                    <span>{f.originalName || f.filename}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {phase === 'scraped' && (
        <>
          {scrapedTitle && <h3 className="creatorTitle">{scrapedTitle}</h3>}

          {contextScore < 5 && (
            <div className="creatorContextWarning">
              Niewystarczajacy kontekst (ocena: {contextScore}/10). Dodaj wiecej informacji:
              <div className="contextInputRow">
                <input
                  type="text"
                  placeholder="Opisz kontekst, np. co sie stalo, gdzie, kiedy..."
                  value={extraContext}
                  onChange={(e) => setExtraContext(e.target.value)}
                  className="creatorContextInput"
                />
                <button onClick={reanalyzeWithContext} disabled={loading} className="creatorBtn">
                  {loading ? 'Analizuje...' : 'Ponowna analiza'}
                </button>
              </div>
            </div>
          )}

          <div className="creatorSection">
            <h3>Tekst zrodlowy</h3>
            <textarea
              className="creatorTextarea"
              value={scrapedText}
              onChange={(e) => setScrapedText(e.target.value)}
              rows={8}
            />
          </div>

          {mediaItems.length > 0 && (
            <div className="creatorSection">
              <h3>Media ({selectedMedia.size}/{mediaItems.length} wybranych)</h3>
              <div className="creatorMediaGrid">
                {mediaItems.map((m) => (
                  <div
                    key={m.id}
                    className={`creatorMediaItem ${selectedMedia.has(m.id) ? 'selected' : ''}`}
                    onClick={() => toggleMedia(m.id)}
                  >
                    <img
                      src={API + '/creator/media/' + encodeURIComponent(m.filename)}
                      alt=""
                      onError={(e) => { e.target.style.display = 'none' }}
                    />
                    <div className="mediaCheck">{selectedMedia.has(m.id) ? '✓' : ''}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {uploadedFiles.length > 0 && (
            <div className="creatorSection">
              <h3>Przeslane pliki</h3>
              <div className="creatorMediaGrid">
                {uploadedFiles.map((f, i) => (
                  <div key={i} className="creatorMediaItem selected">
                    <img
                      src={API + '/creator/media/' + encodeURIComponent(f.filename)}
                      alt=""
                      onError={(e) => { e.target.style.display = 'none' }}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="creatorSection">
            <h3>Generuj dla platform</h3>
            <div className="creatorPlatforms">
              {[['telegram', 'Telegram'], ['x', 'X'], ['facebook', 'Facebook']].map(([k, label]) => (
                <label key={k} className="creatorPlatformCheck">
                  <input
                    type="checkbox"
                    checked={platforms[k]}
                    onChange={(e) => setPlatforms((p) => ({ ...p, [k]: e.target.checked }))}
                  />
                  {label}
                </label>
              ))}
            </div>
            <button onClick={generate} disabled={loading} className="creatorBtn primary creatorGenBtn">
              {loading ? 'Generuje...' : 'Generuj posty'}
            </button>
          </div>
        </>
      )}

      {phase === 'done' && result && (
        <div className="creatorDone">
          <div className="creatorSuccess">
            Post utworzony: <strong>{result.id}</strong>
          </div>
          {result.tags && result.tags.length > 0 && <TagList tags={result.tags} />}
          <div className="creatorResults">
            {Object.entries(result.texts || {}).map(([platform, text]) => (
              <div key={platform} className="creatorResultCard">
                <div className="creatorResultHeader">{platform}</div>
                <div className="creatorResultBody">{text}</div>
              </div>
            ))}
          </div>
          <div className="creatorActions">
            <button onClick={() => onCreated && onCreated(result.id)} className="creatorBtn primary">
              Edytuj post
            </button>
            <button onClick={reset} className="creatorBtn">Nowy</button>
          </div>
        </div>
      )}

      {phase !== 'input' && phase !== 'done' && (
        <div className="creatorActions">
          <button onClick={reset} className="creatorBtn">Zacznij od nowa</button>
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [view, setView] = useState('home')
  const [selectedId, setSelectedId] = useState(null)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const { list, loading, error, refresh } = usePostList(5000)

  const handleAdoptFromList = useCallback((postId, platform) => {
    fetch(API + '/posts/' + encodeURIComponent(postId) + '/adopt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platform }),
    })
      .then((r) => r.json())
      .then((d) => {
        refresh()
        setView(platform)
        if (d.id) setSelectedId(d.id)
      })
      .catch((e) => alert(e.message))
  }, [refresh])

  return (
    <div className="app">
      <Sidebar view={view} onView={(v) => { setView(v); setSelectedId(null); setSelectedIds(new Set()) }} />
      <main className="main">
        {view === 'history' ? (
          <HistoryView />
        ) : view === 'scheduled' ? (
          <ScheduledView />
        ) : view === 'calendar' ? (
          <CalendarView />
        ) : view === 'rss' ? (
          <RssView />
        ) : view === 'templates' ? (
          <TemplatesView />
        ) : view === 'creator' ? (
          <CreatorView onCreated={(id) => { setView('home'); setSelectedId(id) }} />
        ) : selectedId != null ? (
          <PostDetail
            postId={selectedId}
            onBack={(id) => setSelectedId(id)}
            refreshList={refresh}
          />
        ) : (
          <>
            <BulkActionBar selectedIds={selectedIds} setSelectedIds={setSelectedIds} refreshList={refresh} />
            <PostList
              list={list}
              loading={loading}
              error={error}
              view={view}
              onSelect={setSelectedId}
              onAdoptFromList={handleAdoptFromList}
              refreshList={refresh}
              selectedIds={selectedIds}
              setSelectedIds={setSelectedIds}
            />
          </>
        )}
      </main>
    </div>
  )
}
