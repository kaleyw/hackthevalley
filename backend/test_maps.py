"""Map acceptance checks using isolated SQLite and HTTP clients; no outbound calls."""
import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.app import db, main, maps, map_store as store
from backend.app.responder import app as responder_app

KEY = 'test-operator-secret-with-at-least-32-characters'
HEADERS = {'X-Map-Operator-Key': KEY}


class MapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(db, 'DB_PATH', Path(self.temp.name) / 'events.db')
        self.key_patch = patch.object(maps, 'operator_secret', return_value=KEY)
        self.path_patch.start()
        self.key_patch.start()
        db.init()
        store.init()
        self.client = TestClient(main.app)
        self.responder = TestClient(responder_app)

    def tearDown(self):
        self.client.close()
        self.responder.close()
        self.key_patch.stop()
        self.path_patch.stop()
        self.temp.cleanup()

    def create(self, camera='test-cam'):
        response = self.client.post('/events', json={'camera_id': camera, 'location': 'Union Station', 'detected_at': db.now(), 'track_id': 1})
        self.assertEqual(response.status_code, 200)
        return response.json()['id']

    def configure(self, metadata=None, camera='test-cam'):
        response = self.client.put(f'/maps/cameras/{camera}', headers=HEADERS,
            json=metadata or {'kind': 'platform', 'station_id': '1036', 'platform_label': 'Northbound platform', 'direction': 'northbound'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def link(self, event_id):
        response = self.client.post(f'/maps/events/{event_id}/link', headers=HEADERS, json={})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['url']

    def tick(self, at):
        with patch.object(main, 'utcnow', return_value=at):
            asyncio.run(main.watchdog_pass({'cameras': None}))

    def test_unconfigured_cameras_default_to_union_station(self):
        event_id = self.create('new-cam')
        location = self.client.get(f'/maps/events/{event_id}').json()['snapshot']['location']
        self.assertEqual(location['station_name'], 'UNION')
        self.assertEqual(location['coordinates']['precision'], 'station_centroid')

    def test_default_station_can_be_turned_off(self):
        self.client.post('/cameras/old/heartbeat', json={'location': 'Old camera'})
        with patch.dict(os.environ, {'CAMERA_STATION': ''}):
            event_id = self.create('old')
        c = self.client.get(f'/maps/events/{event_id}').json()
        self.assertIsNone(c['snapshot']['location'])
        self.assertIn('location unavailable', c['briefing'])
        self.assertEqual(db.get_event(event_id)['status'], 'open')

    def test_platform_snapshot_uses_official_approximate_station(self):
        configured = self.configure()
        self.assertEqual(configured['station_name'], 'UNION')
        self.assertEqual(configured['coordinates']['precision'], 'station_centroid')
        event_id = self.create()
        before = db.get_event(event_id)
        c = self.client.get(f'/maps/events/{event_id}').json()
        self.assertEqual(c['snapshot']['location'], configured)
        self.assertIn('approximate station location', c['briefing'])
        self.assertEqual(db.get_event(event_id), before)

    def test_accept_arrive_resolve_and_dismiss_unchanged(self):
        event_id = self.create()
        self.assertEqual(self.client.post(f'/events/{event_id}/resolve', json={'outcome': 'person_ok'}).status_code, 409)
        for action, body, status in [('acknowledge', {'actor': 'Tester'}, 'acknowledged'), ('arrive', {}, 'on_scene'), ('resolve', {'outcome': 'person_ok'}, 'resolved')]:
            response = self.client.post(f'/events/{event_id}/{action}', json=body)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status'], status)
        second = self.create('other')
        self.assertEqual(self.client.post(f'/events/{second}/dismiss', json={}).status_code, 422)
        self.assertEqual(self.client.post(f'/events/{second}/dismiss', json={'reason': 'Test false alarm'}).json()['status'], 'dismissed')

    def test_manual_escalation_generates_one_reused_handoff(self):
        event_id = self.create()
        self.client.post(f'/events/{event_id}/escalate', json={})
        row = store.handoff(event_id)
        self.assertEqual(row['escalation_seen'], 1)
        first_link = self.link(event_id)
        maps.on_escalation(event_id)
        self.assertEqual(self.link(event_id), first_link)
        self.assertEqual(store.handoff(event_id)['nonce'], row['nonce'])
        self.assertEqual(db.get_event(event_id)['escalation_level'], 1)
        status = maps.handoff_status(event_id)
        self.assertEqual(status['delivery'], 'unsupported')
        self.assertIsNone(status['attempted_at'])
        self.assertIsNone(status['delivered_at'])
        self.assertIsNone(status['responder_acknowledged_at'])

    def test_automatic_ack_timeout_keeps_exact_existing_boundary(self):
        event_id = self.create()
        event = db.get_event(event_id)
        created = datetime.fromisoformat(event['created_at'])
        self.tick(created + main.ACK_TIMEOUT)
        self.assertEqual(db.get_event(event_id)['escalation_level'], 0)
        self.tick(created + main.ACK_TIMEOUT + timedelta(milliseconds=1))
        self.assertEqual(db.get_event(event_id)['escalation_level'], 1)
        self.assertTrue(store.handoff(event_id))
        row = store.handoff(event_id)
        self.tick(created + main.ACK_TIMEOUT + timedelta(minutes=1))
        self.assertEqual(store.handoff(event_id), row)
        self.assertEqual(db.get_event(event_id)['escalation_level'], 1)

    def test_accepted_alerts_never_auto_escalate(self):
        # Once someone accepts, they know where to go: no automatic escalation, however long
        # it takes to arrive. A responder can still escalate manually, which prepares the map handoff.
        event_id = self.create()
        event = self.client.post(f'/events/{event_id}/acknowledge', json={}).json()
        accepted = datetime.fromisoformat(event['acknowledged_at'])
        self.tick(accepted + timedelta(hours=1))
        self.assertEqual(db.get_event(event_id)['escalation_level'], 0)
        self.assertEqual(self.client.post(f'/events/{event_id}/escalate', json={}).json()['escalation_level'], 1)
        self.assertTrue(store.handoff(event_id))
        second = self.create('helped')
        accepted = self.client.post(f'/events/{second}/acknowledge', json={}).json()
        self.client.post(f'/events/{second}/help-detected')
        self.tick(datetime.fromisoformat(accepted['acknowledged_at']) + timedelta(hours=1))
        self.assertEqual(db.get_event(second)['escalation_level'], 0)

    def test_map_failure_does_not_prevent_either_escalation_path(self):
        with patch.object(maps, 'on_escalation', side_effect=RuntimeError('Map unavailable')):
            manual = self.create()
            response = self.client.post(f'/events/{manual}/escalate', json={})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['escalation_level'], 1)
            auto = self.create('auto')
            created = datetime.fromisoformat(db.get_event(auto)['created_at'])
            self.tick(created + main.ACK_TIMEOUT + timedelta(seconds=1))
            self.assertEqual(db.get_event(auto)['escalation_level'], 1)
        for event_id in (manual, auto):
            before = db.get_event(event_id)
            response = self.client.get(f'/maps/events/{event_id}')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['handoff']['state'], 'generated')
            self.assertEqual(db.get_event(event_id), before)

    def test_map_capture_failure_does_not_block_incident(self):
        with patch.object(maps, 'capture', side_effect=RuntimeError('Map store down')):
            event_id = self.create()
        self.assertEqual(db.get_event(event_id)['status'], 'open')

    def test_map_reads_and_links_do_not_change_lifecycle_or_timers(self):
        self.configure()
        event_id = self.create()
        before = db.get_event(event_id)
        self.client.get(f'/maps/events/{event_id}')
        self.link(event_id)
        self.assertEqual(db.get_event(event_id), before)

    def test_restricted_access_scope_expiration_revocation_and_renewal(self):
        event_id = self.create()
        other = self.create('other')
        url = self.link(event_id)
        token = url.split('#token=')[1]
        header = {'X-Responder-Token': token}
        path = f'/api/responder/events/{event_id}'
        self.assertEqual(self.responder.get(path).status_code, 404)
        self.assertEqual(self.responder.get(path, headers={'X-Responder-Token': 'forged'}).status_code, 404)
        response = self.responder.get(path, headers=header)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn('log', response.json()['incident'])
        self.assertNotIn('assigned_to', response.json()['incident'])
        self.assertEqual(self.responder.get(f'/api/responder/events/{other}', headers=header).status_code, 404)
        for unrelated in ('/api/events', '/events', '/', '/docs', '/ws'):
            self.assertEqual(self.responder.get(unrelated, headers=header).status_code, 404)
        self.assertEqual(self.responder.post(f'/api/responder/events/{event_id}', headers=header).status_code, 405)
        with patch.object(maps, 'now', return_value=maps.now() + maps.LINK_TTL + timedelta(seconds=1)):
            self.assertEqual(self.responder.get(path, headers=header).status_code, 404)
        self.client.delete(f'/maps/events/{event_id}/link', headers=HEADERS)
        maps.on_escalation(event_id)  # another escalation must not silently undo revocation
        self.assertEqual(self.responder.get(path, headers=header).status_code, 404)
        response = self.client.post(f'/maps/events/{event_id}/link', headers=HEADERS, json={'renew': True})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()['url'], url)
        self.assertEqual(self.responder.get(path, headers=header).status_code, 404)

    def test_operator_permissions_and_coordinate_validation(self):
        self.assertEqual(self.client.put('/maps/cameras/cam', json={'kind': 'platform'}).status_code, 401)
        self.assertEqual(self.client.put('/maps/cameras/cam', headers=HEADERS, json={'kind': 'platform', 'coordinates': {'lat': 100, 'lon': 0, 'precision': 'approximate'}}).status_code, 422)
        self.assertEqual(self.client.put('/maps/cameras/cam', headers=HEADERS, json={'kind': 'platform', 'meeting_point': {'label': 'Unverified entrance', 'verified': False}}).status_code, 422)

    def test_late_location_updates_handoff_without_replacing_snapshot(self):
        event_id = self.create()
        self.client.post(f'/events/{event_id}/escalate', json={})
        token = self.link(event_id).split('#token=')[1]
        snapshot = store.incident(event_id)['snapshot']
        response = self.client.put(f'/maps/events/{event_id}/location', headers=HEADERS, json={'kind': 'platform', 'station_name': 'QUEEN'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(store.incident(event_id)['snapshot'], snapshot)
        result = self.responder.get(f'/api/responder/events/{event_id}', headers={'X-Responder-Token': token})
        self.assertIn('Queen Station', result.json()['briefing'])


if __name__ == '__main__':
    unittest.main()
