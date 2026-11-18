import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile


def parse_time(value, label):
    if not isinstance(value, str):
        raise ValueError(f'{label} must be a string.')
    if value.endswith('Z'):
        value = value[:-1] + '+00:00'
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is not None:
            return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ValueError(f'{label} is not a valid ISO timestamp.') from None
    raise ValueError(f'{label} needs a time zone.')


def utc_text(value):
    return value.isoformat().replace('+00:00', 'Z')


def required_text(row, field):
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'The {field} field needs a nonempty string.')
    return value


@dataclass(frozen=True)
class Record:
    id: str
    source: str
    kind: str
    timestamp: datetime
    received_at: datetime
    message: str

    @classmethod
    def from_row(cls, row, now):
        if not isinstance(row, dict):
            raise ValueError('The record must be a JSON object.')
        record_id = required_text(row, 'id')
        source = required_text(row, 'source')
        kind = row.get('kind')
        if kind not in ('event', 'heartbeat'):
            raise ValueError('The kind field must be event or heartbeat.')
        timestamp = parse_time(row.get('timestamp'), 'Timestamp')
        received_at = parse_time(row.get('received_at'), 'Receipt timestamp')
        if timestamp > received_at:
            raise ValueError('Timestamp is after receipt.')
        if received_at > now:
            raise ValueError('Receipt timestamp is after the incident clock.')
        return cls(record_id, source, kind, timestamp, received_at, required_text(row, 'message'))

    def public_record(self, late_after):
        return {
            'id': self.id,
            'source': self.source,
            'kind': self.kind,
            'timestamp': utc_text(self.timestamp),
            'received_at': utc_text(self.received_at),
            'message': self.message,
            'lag_seconds': self.lag_seconds,
            'late': self.is_late(late_after),
        }

    @property
    def lag_seconds(self):
        return (self.received_at - self.timestamp).total_seconds()

    def is_late(self, late_after):
        return self.kind == 'event' and self.lag_seconds >= late_after


def source_summary(source, entries, now, stale_after, late_after):
    events = [entry for entry in entries if entry.kind == 'event']
    heartbeats = [entry for entry in entries if entry.kind == 'heartbeat']
    latest_event = events[-1].timestamp if events else None
    latest_heartbeat = heartbeats[-1].timestamp if heartbeats else None
    event_age = (now - latest_event).total_seconds() if latest_event is not None else None
    heartbeat_age = (now - latest_heartbeat).total_seconds() if latest_heartbeat is not None else None
    status = 'no-data'
    if event_age is not None:
        status = 'stale' if event_age >= stale_after else 'fresh'
    return {
        'source': source,
        'status': status,
        'latest_event_at': utc_text(latest_event) if latest_event is not None else None,
        'latest_heartbeat_at': utc_text(latest_heartbeat) if latest_heartbeat is not None else None,
        'event_age_seconds': event_age,
        'heartbeat_age_seconds': heartbeat_age,
        'events': len(events),
        'heartbeats': len(heartbeats),
        'late_events': sum(entry.is_late(late_after) for entry in events),
    }


def build_replay(lines, now, stale_after=120, late_after=60):
    records = []
    rejected = []
    duplicates = []
    seen = set()
    by_source = {}

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        source = None
        try:
            row = json.loads(line)
            possible_source = row.get('source') if isinstance(row, dict) else None
            if isinstance(possible_source, str) and possible_source.strip():
                source = possible_source
                by_source.setdefault(source, [])
            record = Record.from_row(row, now)
        except (json.JSONDecodeError, RecursionError):
            rejected.append({'line': line_number, 'source': None, 'reason': 'Invalid JSON.'})
            continue
        except ValueError as exc:
            rejected.append({'line': line_number, 'source': source, 'reason': str(exc)})
            continue

        if record.id in seen:
            duplicates.append({'line': line_number, 'source': record.source, 'id': record.id})
            continue
        seen.add(record.id)
        records.append(record)

    timeline = []
    for record in sorted(records, key=lambda record: record.timestamp):
        public = record.public_record(late_after)
        timeline.append(public)
        by_source[record.source].append(record)

    return {
        'as_of': utc_text(now),
        'stale_after_seconds': stale_after,
        'late_after_seconds': late_after,
        'sources': [
            source_summary(source, by_source[source], now, stale_after, late_after)
            for source in sorted(by_source)
        ],
        'records': timeline,
        'rejected': rejected,
        'duplicates': duplicates,
    }


def positive_seconds(value):
    try:
        seconds = int(value)
    except ValueError:
        seconds = 0
    if seconds < 1:
        raise argparse.ArgumentTypeError('use a positive whole number of seconds')
    return seconds


def save_replay(output, replay):
    content = json.dumps(replay, indent=2, ensure_ascii=False) + '\n'
    if output is None:
        sys.stdout.write(content)
        return

    temporary = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=output.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check a fictional log feed and build a Dead Channel replay.')
    parser.add_argument('input', type=Path, help='Path to the JSONL log file.')
    parser.add_argument('--now', required=True, help='Incident clock as an ISO timestamp with a time zone.')
    parser.add_argument('--stale-after', type=positive_seconds, default=120, help='Seconds before a source turns stale (default 120).')
    parser.add_argument('--late-after', type=positive_seconds, default=60, help='Seconds of delay before an event counts as late (default 60).')
    parser.add_argument('--output', type=Path, help='Replay JSON path. Omit to write JSON to standard output.')
    args = parser.parse_args(argv)

    try:
        now = parse_time(args.now, 'Incident clock')
        if args.output is not None and args.input.resolve() == args.output.resolve():
            raise ValueError('Choose a different path for the replay and input file.')
        with args.input.open(encoding='utf-8-sig') as lines:
            replay = build_replay(lines, now, args.stale_after, args.late_after)
        save_replay(args.output, replay)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(
        f"{len(replay['sources'])} sources, {len(replay['records'])} records, "
        f"{len(replay['rejected'])} rejected, {len(replay['duplicates'])} duplicates.",
        file=sys.stderr,
    )


if __name__ == '__main__':
    main()
