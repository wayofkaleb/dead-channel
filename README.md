# Dead Channel

The Emberlane monitoring desk is quiet. Check the heartbeat, the age of the latest events, and the rows the collector rejected before you decide why.

[Play Dead Channel on Midnight Packet](https://midnightpacket.dev/labs/dead-channel/)

## Run locally

From this repo, run the Python tool on the same fictional logs used by the browser lab. The fixed clock gives you the same replay every time. The tool uses Python's standard library.

```sh
python dead_channel.py samples/quiet-desk.jsonl --now 2026-01-18T00:00:00Z --output replay.json
```

Then start a local server to play the case with that replay.

```sh
python -m http.server 8000 --bind 127.0.0.1
```

Open [the local demo](http://127.0.0.1:8000/). Run the tests from the repo root.

```sh
python -m unittest discover -s tests
```

## Read the replay

The tool tracks when an event happened and when the collector received it. It reports event and heartbeat ages separately. The fixture includes late data, a duplicate, and bad timestamps so you can see how those cases affect the replay.

[Debugging notes and case answer](debugging-notes.md)
