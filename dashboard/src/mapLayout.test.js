import test from 'node:test'
import assert from 'node:assert/strict'
import { groupIncidents, uniqueTrains } from './mapLayout.js'

const incident = (id, status, lat = 43.64575, lon = -79.37923) => ({
  incident: { id, status },
  snapshot: { location: { coordinates: { lat, lon } } },
})

test('all incidents at Union remain individually present, with active alerts first', () => {
  const groups = groupIncidents([incident(1, 'resolved'), incident(2, 'dismissed'), incident(3, 'acknowledged')])
  assert.equal(groups.length, 1)
  assert.deepEqual(groups[0].contexts.map((c) => c.incident.id), [3, 2, 1])
  assert.deepEqual(groups[0].coordinates, { lat: 43.64575, lon: -79.37923 })
})

test('different stations remain separate; unknown locations are not fabricated', () => {
  const groups = groupIncidents([incident(1, 'open'), incident(2, 'open', 43.65, -79.38), { incident: { id: 3 } }])
  assert.equal(groups.length, 2)
  assert.deepEqual(groups.map((g) => g.contexts[0].incident.id), [1, 2])
})

test('confirmed transfer moves only current location, preserving the snapshot', () => {
  const context = incident(1, 'open')
  context.transfer = { location: { coordinates: { lat: 43.66, lon: -79.39 } } }
  const snapshot = structuredClone(context.snapshot)
  assert.equal(groupIncidents([context])[0].coordinates.lat, 43.66)
  assert.deepEqual(context.snapshot, snapshot)
})

test('all associated trains are included once, using the newest sample per train', () => {
  const a = { latest_train: { latest: { train_id: 'T1', lat: 43.65, lon: -79.38, observed_at: '2026-10-17T18:00:00Z' } } }
  const b = { latest_train: { latest: { train_id: 'T1', lat: 43.66, lon: -79.38, observed_at: '2026-10-17T18:00:02Z' } } }
  const c = { latest_train: { latest: { train_id: 'T2', lat: 43.67, lon: -79.38, observed_at: '2026-10-17T18:00:02Z' } } }
  assert.deepEqual(uniqueTrains([a, c, b]), [b, c])
})
