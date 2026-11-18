import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from dead_channel import build_replay, parse_time


PROJECT = Path(__file__).resolve().parents[1]
NOW_TEXT = '2026-01-18T00:00:00Z'
NOW = parse_time(NOW_TEXT, 'Incident clock')


def log_line(record_id, timestamp, **fields):
    row = {
        'id': record_id,
        'source': 'sessions',
        'kind': 'event',
        'timestamp': timestamp,
        'received_at': NOW_TEXT,
        'message': 'A fictional log entry.',
    }
    row.update(fields)
    return json.dumps(row)


class ReplayTests(unittest.TestCase):
    def test_stale_boundary_does_not_depend_on_heartbeat(self):
        result = build_replay([
            log_line('pulse', '2026-01-17T23:59:54Z', kind='heartbeat'),
            log_line('old', '2026-01-17T23:58:00Z'),
            log_line('almost', '2026-01-17T23:58:01Z', source='network'),
            log_line('pulse-only', '2026-01-17T23:59:52Z', source='archive', kind='heartbeat'),
        ], NOW)
        sources = {source['source']: source for source in result['sources']}
        self.assertEqual(sources['sessions']['status'], 'stale')
        self.assertEqual(sources['sessions']['event_age_seconds'], 120)
        self.assertEqual(sources['sessions']['heartbeat_age_seconds'], 6)
        self.assertEqual(sources['network']['status'], 'fresh')
        self.assertEqual(sources['archive']['status'], 'no-data')
        self.assertIsNone(sources['archive']['latest_event_at'])

    def test_timezone_conversion_and_order_are_stable(self):
        result = build_replay([
            log_line('tied-first-in-file', '2026-01-18T01:59:59+02:00'),
            log_line('fractional', '2026-01-17T23:59:59.5Z'),
            log_line('earlier', '2026-01-17T18:58:00-05:00'),
            log_line('tied-last-in-file', '2026-01-17T23:59:59Z'),
        ], NOW)
        records = result['records']
        self.assertEqual([record['id'] for record in records], [
            'earlier', 'tied-first-in-file', 'tied-last-in-file', 'fractional',
        ])
        self.assertEqual(records[0]['timestamp'], '2026-01-17T23:58:00Z')
        self.assertEqual(records[1]['timestamp'], '2026-01-17T23:59:59Z')
        self.assertTrue(records[-1]['timestamp'].endswith('Z'))
        self.assertEqual(records[-1]['lag_seconds'], 0.5)

    def test_rejection_duplicate_and_late_boundaries(self):
        result = build_replay([
            log_line('at-boundary', '2026-01-17T23:59:00Z'),
            log_line('within-window', '2026-01-17T23:59:01Z'),
            log_line('at-boundary', '2026-01-17T23:59:00Z'),
            'not JSON',
            log_line('bad-time', '2026-02-30T23:59:00Z', source='backfill'),
            log_line('from-future', '2026-01-18T00:10:00Z'),
            log_line('after-clock', '2026-01-17T23:59:50Z', received_at='2026-01-18T01:00:00Z'),
            log_line('no-zone', '2026-01-17T23:59:00'),
            '',
        ], NOW)
        self.assertEqual([record['late'] for record in result['records']], [True, False])
        self.assertEqual(result['duplicates'], [{'line': 3, 'source': 'sessions', 'id': 'at-boundary'}])
        self.assertEqual([row['line'] for row in result['rejected']], [4, 5, 6, 7, 8])
        self.assertEqual(result['rejected'][1]['source'], 'backfill')
        self.assertEqual(result['sources'][0]['status'], 'no-data')
        self.assertEqual(result['sources'][1]['late_events'], 1)

    def test_export_is_deterministic_and_preserves_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'desk.jsonl'
            source.write_text(log_line('first', '2026-01-17T23:57:00Z') + '\n', encoding='utf-8')
            destination = Path(directory) / 'replay.json'
            command = [sys.executable, str(PROJECT / 'dead_channel.py'), str(source), '--now', NOW_TEXT]
            first = subprocess.run(command + ['--output', str(destination)], capture_output=True, check=True)
            file_contents = destination.read_bytes()
            second = subprocess.run(command, capture_output=True, check=True)
            self.assertEqual(file_contents, second.stdout.replace(b'\r\n', b'\n'))
            self.assertEqual(first.stdout, b'')
            self.assertEqual(json.loads(file_contents)['sources'][0]['status'], 'stale')
            original = source.read_bytes()
            blocked = subprocess.run(command + ['--output', str(source)], capture_output=True, check=False)
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(source.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
