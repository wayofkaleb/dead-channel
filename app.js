const byId = id => document.getElementById(id);
const viewButtons = [...document.querySelectorAll('[data-view]')];
const form = byId('diagnosis-form');
const sourceFilter = byId('source-filter');
const checkButton = byId('check-diagnosis');
const feedback = byId('diagnosis-feedback');
const status = byId('replay-status');

const statusLabels = { fresh: 'Fresh', stale: 'Stale', 'no-data': 'No events' };

function element(tag, copy, className = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = copy;
  return node;
}

function utcTime(timestamp) {
  return timestamp ? `${timestamp.split('T')[1].replace('Z', '')} UTC` : 'No record';
}

function age(seconds) {
  if (seconds === null) return 'No record';
  const value = Math.floor(seconds);
  if (value < 60) return `${value}s ago`;
  return `${Math.floor(value / 60)}m ${value % 60}s ago`;
}

function timeEntry(label, timestamp, seconds) {
  const item = document.createElement('div');
  const value = timestamp ? `${utcTime(timestamp)} · ${age(seconds)}` : 'No record';
  item.append(element('dt', label), element('dd', value));
  return item;
}

function showView(view) {
  for (const button of viewButtons) {
    const active = button.dataset.view === view;
    button.setAttribute('aria-pressed', String(active));
    byId(button.dataset.view).hidden = !active;
  }
}

function listItem(heading, copy) {
  const item = document.createElement('li');
  item.append(element('p', heading, 'lab-note'), element('p', copy, 'record-message'));
  return item;
}

function renderFeeds(replay) {
  byId('feed-intro').textContent = `Events go stale at ${replay.stale_after_seconds}s. Heartbeats have their own clock.`;
  const feeds = replay.sources.map(feed => {
    const item = document.createElement('li');
    item.className = 'feed-card';
    item.dataset.status = feed.status;
    const heading = document.createElement('div');
    heading.className = 'feed-heading';
    heading.append(element('strong', feed.source), element('span', statusLabels[feed.status], 'lab-tag'));
    const times = document.createElement('dl');
    times.className = 'feed-times';
    times.append(
      timeEntry('Last event', feed.latest_event_at, feed.event_age_seconds),
      timeEntry('Last heartbeat', feed.latest_heartbeat_at, feed.heartbeat_age_seconds)
    );
    item.append(heading, times);
    return item;
  });
  byId('feed-list').replaceChildren(...feeds);
}

function renderAccepted(replay) {
  const records = replay.records
    .filter(record => !sourceFilter.value || record.source === sourceFilter.value)
    .reverse();
  const items = records.map(record => {
    const late = record.late ? ` · arrived ${record.lag_seconds}s late` : '';
    return listItem(`${utcTime(record.timestamp)} · ${record.source} · ${record.kind}${late}`, record.message);
  });
  byId('accepted-list').replaceChildren(...(items.length ? items : [element('li', 'No accepted records.')]));
}

function renderRejected(replay) {
  const rejected = replay.rejected.map(record => {
    return listItem(`Line ${record.line} · ${record.source || 'Unknown source'}`, record.reason);
  });
  const duplicates = replay.duplicates.map(record => {
    return listItem(`Line ${record.line} · ${record.source}`, `Repeated ID ${record.id}. The first copy is in Accepted logs.`);
  });
  byId('rejected-list').replaceChildren(...(rejected.length ? rejected : [element('li', 'No rejected records.')]));
  byId('duplicate-list').replaceChildren(...(duplicates.length ? duplicates : [element('li', 'No duplicate records.')]));
}

function isTimestamp(value) {
  return typeof value === 'string' && /T.*Z$/.test(value) && Number.isFinite(Date.parse(value));
}

function isOptionalTimestamp(value) {
  return value === null || isTimestamp(value);
}

function isAge(value) {
  return value === null || (Number.isFinite(value) && value >= 0);
}

function checkReplay(replay) {
  if (!replay || !isTimestamp(replay.as_of) || !Number.isFinite(replay.stale_after_seconds) ||
      replay.stale_after_seconds <= 0 || !Number.isFinite(replay.late_after_seconds) ||
      replay.late_after_seconds <= 0 || !Array.isArray(replay.sources) || !Array.isArray(replay.records) ||
      !Array.isArray(replay.rejected) || !Array.isArray(replay.duplicates)) {
    throw new Error('Missing replay fields');
  }
  if (replay.sources.some(feed => !feed || typeof feed.source !== 'string' ||
      !Object.hasOwn(statusLabels, feed.status) || !isOptionalTimestamp(feed.latest_event_at) ||
      !isOptionalTimestamp(feed.latest_heartbeat_at) || !isAge(feed.event_age_seconds) ||
      !isAge(feed.heartbeat_age_seconds)) ||
      replay.records.some(record => !record || typeof record.source !== 'string' ||
        !['event', 'heartbeat'].includes(record.kind) || !isTimestamp(record.timestamp) ||
        typeof record.message !== 'string' || !Number.isFinite(record.lag_seconds) ||
        typeof record.late !== 'boolean') ||
      replay.rejected.some(record => !record || !Number.isInteger(record.line) ||
        (record.source !== null && typeof record.source !== 'string') || typeof record.reason !== 'string') ||
      replay.duplicates.some(record => !record || !Number.isInteger(record.line) ||
        typeof record.source !== 'string' || typeof record.id !== 'string')) {
    throw new Error('Invalid replay records');
  }
  const gateway = replay.sources.find(feed => feed.source === 'game-gateway');
  if (!gateway || gateway.status !== 'stale' || gateway.event_age_seconds === null ||
      gateway.heartbeat_age_seconds === null || gateway.heartbeat_age_seconds >= replay.stale_after_seconds ||
      !replay.rejected.some(record => record.source === gateway.source && /timestamp/i.test(record.reason))) {
    throw new Error('Case evidence is missing');
  }
}

function startDesk(replay) {
  byId('replay-clock').textContent = replay.as_of.replace('T', ' ').replace('Z', ' UTC');
  byId('accepted-intro').textContent = `Newest event time first. A record is late when it arrives ${replay.late_after_seconds}s or more after its event time.`;
  const gateway = replay.sources.find(feed => feed.source === 'game-gateway');
  const gatewayRejects = replay.rejected.filter(record => record.source === gateway.source);
  renderFeeds(replay);
  renderRejected(replay);
  for (const feed of replay.sources) {
    const option = element('option', feed.source);
    option.value = feed.source;
    sourceFilter.append(option);
  }
  renderAccepted(replay);
  byId('desk').hidden = false;
  status.textContent = '';

  for (const button of viewButtons) {
    button.addEventListener('click', () => showView(button.dataset.view));
  }
  sourceFilter.addEventListener('change', () => renderAccepted(replay));
  form.addEventListener('change', () => {
    checkButton.disabled = false;
    feedback.hidden = true;
  });
  form.addEventListener('submit', event => {
    event.preventDefault();
    const selection = new FormData(form).get('diagnosis');
    if (!selection) return;
    const correct = selection === 'rejected';
    const clue = selection === 'collector'
      ? 'Check the heartbeats. The collector is still sending them, and the other feeds have fresh events.'
      : 'Check Rejected logs. The gateway has incoming records that never made it into the accepted feed.';
    const count = gatewayRejects.length;
    const finding = `The last gateway event was ${age(gateway.event_age_seconds)}, but its heartbeat was ${age(gateway.heartbeat_age_seconds)}. The gateway had ${count} rejected ${count === 1 ? 'line' : 'lines'}. Check the timestamp in those records next.`;
    byId('feedback-heading').textContent = correct ? 'You found the gap.' : 'Take another look.';
    byId('feedback-copy').textContent = correct ? finding : clue;
    feedback.hidden = false;
    byId('feedback-heading').focus();
  });
  form.addEventListener('reset', () => {
    sourceFilter.value = '';
    renderAccepted(replay);
    showView('feeds');
    checkButton.disabled = true;
    feedback.hidden = true;
    viewButtons[0].focus();
  });
}

async function loadReplay() {
  status.textContent = 'Opening the case replay…';
  try {
    const response = await fetch('replay.json');
    if (!response.ok) throw new Error('Replay request failed');
    const replay = await response.json();
    checkReplay(replay);
    startDesk(replay);
  } catch {
    byId('replay-clock').textContent = 'Replay unavailable';
    status.textContent = location.protocol === 'file:'
      ? 'Open this lab from the local HTTP server described in the README.'
      : 'Could not load the case replay. Refresh the page to try again.';
  }
}

loadReplay();
