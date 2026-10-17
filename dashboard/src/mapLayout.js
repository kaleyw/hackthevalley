// Shared coordinates stay geographically accurate; each incident gets its own label.
export const effectiveLocation = (context) => context?.transfer?.location ?? context?.supplemental ?? context?.snapshot?.location
export const detectionCoordinates = (context) => context?.snapshot?.train_position ?? context?.snapshot?.location?.coordinates
export const currentCoordinates = (context) => effectiveLocation(context)?.coordinates ?? detectionCoordinates(context) ?? context?.latest_train?.latest
const located = (c) => Number.isFinite(c?.lat) && Number.isFinite(c?.lon)
const closed = (context) => ['resolved', 'dismissed'].includes(context.incident.status)

export function groupIncidents(contexts) {
  const groups = new Map()
  for (const context of contexts) {
    const coordinates = currentCoordinates(context)
    if (!located(coordinates)) continue
    const key = `${coordinates.lat.toFixed(5)},${coordinates.lon.toFixed(5)}`
    if (!groups.has(key)) groups.set(key, { coordinates, contexts: [] })
    groups.get(key).contexts.push(context)
  }
  for (const group of groups.values()) {
    group.contexts.sort((a, b) => Number(closed(a)) - Number(closed(b)) || b.incident.id - a.incident.id)
  }
  return [...groups.values()]
}

export function uniqueTrains(contexts) {
  const trains = new Map()
  for (const context of contexts) {
    const latest = context.latest_train?.latest
    if (!located(latest)) continue
    const previous = trains.get(latest.train_id)
    if (!previous || Date.parse(latest.observed_at) > Date.parse(previous.latest_train.latest.observed_at)) {
      trains.set(latest.train_id, context)
    }
  }
  return [...trains.values()]
}
