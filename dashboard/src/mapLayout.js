// Shared coordinates stay geographically accurate; each incident gets its own label.
export const effectiveLocation = (context) => context?.supplemental ?? context?.snapshot?.location
export const detectionCoordinates = (context) => context?.snapshot?.location?.coordinates
export const currentCoordinates = (context) => effectiveLocation(context)?.coordinates ?? detectionCoordinates(context)
// Station data uses upper case ("UNION"); show it the way people say it ("Union Station")
export const stationName = (name) => name ? `${name.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase())} Station` : null
const located = (c) => Number.isFinite(c?.lat) && Number.isFinite(c?.lon)
const closed = (context) => ['resolved', 'dismissed'].includes(context.incident.status)

export function groupIncidents(contexts) {
  const groups = new Map()
  for (const context of contexts) {
    const coordinates = currentCoordinates(context)
    if (!located(coordinates)) continue
    const key = `${coordinates.lat.toFixed(5)},${coordinates.lon.toFixed(5)}`
    if (!groups.has(key)) groups.set(key, { coordinates, station: stationName(effectiveLocation(context)?.station_name), contexts: [] })
    groups.get(key).contexts.push(context)
  }
  for (const group of groups.values()) {
    group.contexts.sort((a, b) => Number(closed(a)) - Number(closed(b)) || b.incident.id - a.incident.id)
  }
  return [...groups.values()]
}
