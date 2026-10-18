"""Check configuration-only rehearsals never create artificial incidents."""
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import Mock, patch


class DemoCliTests(unittest.TestCase):
    def test_configure_only_never_creates_events_or_starts_simulator(self):
        script = Path(__file__).with_name('map_demo.py')
        for kind in ('platform', 'train'):
            with self.subTest(kind=kind):
                response = Mock(ok=True)
                response.json.return_value = {}
                with (patch.dict(os.environ, {'MAP_OPERATOR_KEY': 'test-only-secret-with-more-than-24-characters'}),
                      patch('dotenv.dotenv_values', return_value={}),
                      patch('requests.request', return_value=response) as request,
                      patch('sys.argv', [str(script), '--kind', kind, '--camera-id', 'cam-1', '--configure-only']),
                      patch('builtins.print')):
                    runpy.run_path(str(script), run_name='__main__')
                request.assert_called_once()
                self.assertEqual(request.call_args.args, ('PUT', 'http://localhost:8000/maps/cameras/cam-1'))


if __name__ == '__main__':
    unittest.main()
