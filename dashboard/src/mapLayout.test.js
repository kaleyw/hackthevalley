import test from 'node:test'
import assert from 'node:assert/strict'
import { groupIncidents, stationName } from './mapLayout.js'

const incident = (id, status, lat = 43.64575, lon = -79.37923, station_name = 'UNION') => ({
  incident: { id, status },
  snapshot: { location: { station_name, coordinates: { lat, lon } } },
})

test('all incidents at Union remain individually present, with active alerts first', () => {
  const groups = groupIncidents([incident(1, 'resolved'), incident(2, 'dismissed'), incident(3, 'acknowledged')])
  assert.equal(groups.length, 1)
  assert.deepEqual(groups[0].contexts.map((c) => c.incident.id), [3, 2, 1])
  assert.deepEqual(groups[0].coordinates, { lat: 43.64575, lon: -79.37923 })
  assert.equal(groups[0].station, 'Union Station')
})

test('different stations remain separate; unknown locations are not fabricated', () => {
  const groups = groupIncidents([incident(1, 'open'), incident(2, 'open', 43.65, -79.38, 'KING'), { incident: { id: 3 } }])
  assert.equal(groups.length, 2)
  assert.deepEqual(groups.map((g) => g.contexts[0].incident.id), [1, 2])
})

test('a staff-entered location moves only the current location, preserving the snapshot', () => {
  const context = incident(1, 'open')
  context.supplemental = { coordinates: { lat: 43.66, lon: -79.39 } }
  const snapshot = structuredClone(context.snapshot)
  assert.equal(groupIncidents([context])[0].coordinates.lat, 43.66)
  assert.deepEqual(context.snapshot, snapshot)
})

test('station names read the way people say them', () => {
  assert.equal(stationName('UNION'), 'Union Station')
  assert.equal(stationName('ST GEORGE'), 'St George Station')
  assert.equal(stationName(null), null)
})
