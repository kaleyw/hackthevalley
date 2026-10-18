"""Configure demo camera locations, or create synthetic map incidents locally."""
import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
import requests
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=('platform', 'train'), default='platform')
    parser.add_argument('--camera-id', help='Defaults to a separate demo camera; does not change cam-1')
    parser.add_argument('--configure-only', action='store_true',
                        help='Only assign camera location; do not create an incident or start train simulation')
    args = parser.parse_args()
    if args.configure_only and not args.camera_id:
        parser.error('--configure-only requires an explicit --camera-id (use cam-1 for the webcam)')
    key = os.getenv('MAP_OPERATOR_KEY') or dotenv_values(Path(__file__).resolve().parents[1] / '.env').get('MAP_OPERATOR_KEY')
    if not key or len(key) < 24:
        parser.error('Set MAP_OPERATOR_KEY in .env to a random secret of at least 24 characters')
    headers = {'X-Map-Operator-Key': key}

    def post(path, body, method='POST'):
        try:
            response = requests.request(method, f'http://localhost:8000{path}', headers=headers, json=body, timeout=5)
        except requests.RequestException as exc:
            raise SystemExit('Cannot reach the backend at http://localhost:8000. Start the main backend and retry.') from exc
        if not response.ok:
            raise SystemExit(f'Demo request failed ({response.status_code}): {response.text}')
        return response.json()

    camera = args.camera_id or f'demo-{args.kind}'
    if args.kind == 'train':
        if not args.configure_only:
            post('/maps/simulator', {'mode': 'running'})
        metadata = {'kind': 'train', 'train_id': 'DEMO-T1', 'car_id': 'demo-car-1', 'line': '1', 'source': 'simulated'}
        location = 'DEMO · DEMO-T1 / demo-car-1'
    else:
        metadata = {'kind': 'platform', 'station_id': '1036', 'platform_label': 'Demo platform (not a verified platform coordinate)', 'direction': 'northbound', 'line': '1', 'source': 'configured'}
        location = 'DEMO · UNION station, approximate location'
    post(f'/maps/cameras/{camera}', metadata, method='PUT')
    if args.configure_only:
        print(f'Camera {camera} location configured. No synthetic incident created; no simulator started.')
        print('Start vision/run.py; the next camera-detected incident will capture this location.')
        return
    result = post('/events', {'camera_id': camera, 'location': location, 'track_id': 1,
                            'detected_at': datetime.now(timezone.utc).isoformat(), 'type': 'person_down',
                            'urgency': 'medium', 'summary': 'DEMO: possible fall detected',
                            'reasons': ['Synthetic map demonstration; no camera footage or real fall']})
    print(f"Demo incident #{result['id']} ready (duplicate: {result['duplicate']}). Open http://localhost:5173")
    print('Existing escalation is log/dashboard-only. No calls or outbound notifications are configured.')


if __name__ == '__main__':
    main()
