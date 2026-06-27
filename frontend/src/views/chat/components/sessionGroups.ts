export type SessionItem = Record<string, any>

function startOfDay(date: Date) {
  const next = new Date(date)
  next.setHours(0, 0, 0, 0)
  return next
}

export function groupSessions(sessions: SessionItem[]) {
  const now = startOfDay(new Date())
  const day = 24 * 60 * 60 * 1000
  const groups = [
    { key: 'pinned', label: '置顶', items: [] as SessionItem[] },
    { key: 'today', label: '今天', items: [] as SessionItem[] },
    { key: 'yesterday', label: '昨天', items: [] as SessionItem[] },
    { key: 'last7', label: '近 7 天', items: [] as SessionItem[] },
    { key: 'last30', label: '近 30 天', items: [] as SessionItem[] },
    { key: 'earlier', label: '更早', items: [] as SessionItem[] },
  ]
  for (const session of sessions) {
    if (session.is_pinned) {
      groups[0].items.push(session)
      continue
    }
    const raw = session.updated_at || session.created_at
    const date = raw ? startOfDay(new Date(raw)) : now
    const diff = Math.floor((now.getTime() - date.getTime()) / day)
    if (diff <= 0) groups[1].items.push(session)
    else if (diff === 1) groups[2].items.push(session)
    else if (diff <= 7) groups[3].items.push(session)
    else if (diff <= 30) groups[4].items.push(session)
    else groups[5].items.push(session)
  }
  return groups.filter((group) => group.items.length)
}
