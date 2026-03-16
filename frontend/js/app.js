// ── Config ─────────────────────────────────────
const API = 'http://localhost:8000';
const WS_BASE = API.replace(/^http/, 'ws');

// ── Pipeline stages ────────────────────────────
const STAGES = [
  { key: 'A1_INTAKE', label: 'A1 — Intake', status: 'INTAKE_COMPLETE' },
  { key: 'A2_STRUCTURING', label: 'A2 — Structuring', status: 'STRUCTURING' },
  { key: 'A3_GO_NO_GO', label: 'A3 — Go / No-Go', status: 'GO_NO_GO' },
  { key: 'B1_REQUIREMENTS_EXTRACTION', label: 'B1 — Requirement Extract', status: 'EXTRACTING_REQUIREMENTS' },
  { key: 'B2_REQUIREMENTS_VALIDATION', label: 'B2 — Requirement Valid.', status: 'VALIDATING_REQUIREMENTS' },
  { key: 'C1_ARCHITECTURE_PLANNING', label: 'C1 — Architecture Plan', status: 'ARCHITECTURE_PLANNING' },
  { key: 'C2_REQUIREMENT_WRITING', label: 'C2 — Response Writing', status: 'WRITING_RESPONSES' },
  { key: 'C3_NARRATIVE_ASSEMBLY', label: 'C3 — Narrative Assembly', status: 'ASSEMBLING_NARRATIVE' },
  { key: 'D1_TECHNICAL_VALIDATION', label: 'D1 — Technical Validation', status: 'TECHNICAL_VALIDATION' },
  { key: 'E1_COMMERCIAL', label: 'E1 — Commercial Review', status: 'COMMERCIAL_LEGAL_REVIEW' },
  { key: 'E2_LEGAL', label: 'E2 — Legal Review', status: 'COMMERCIAL_LEGAL_REVIEW' },
  { key: 'H1_HUMAN_VALIDATION', label: 'H1 — Human Validation', status: 'AWAITING_HUMAN_VALIDATION' },
  { key: 'F1_FINAL_READINESS', label: 'F1 — Final Readiness', status: 'FINAL_READINESS' },
  { key: 'F2_SUBMISSION', label: 'F2 — Submission', status: 'SUBMITTED' },
];

// ── Helper: format file size ───────────────────
function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

// ── Helper: log to a log-box ───────────────────
function addLog(boxId, msg, cls = '') {
  const box = document.getElementById(boxId);
  const time = new Date().toLocaleTimeString();
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.innerHTML = `<span class="log-time">${time}</span><span class="log-msg ${cls}">${msg}</span>`;
  box.appendChild(entry);
  box.scrollTop = box.scrollHeight;
}

// ── Helper: fetch with error handling ──────────
async function apiFetch(path, opts = {}) {
  try {
    const res = await fetch(`${API}${path}`, opts);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
    return await res.json();
  } catch (e) {
    throw e;
  }
}

function escapeHtml(value = '') {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function jsStringLiteral(value = '') {
  return JSON.stringify(String(value ?? ''));
}

function truncateText(value = '', maxLength = 260) {
  const text = String(value || '').trim();
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength).trimEnd()}...`;
}

async function checkHealth() {
  const dot = document.getElementById('apiDot');
  const label = document.getElementById('apiLabel');
  try {
    await apiFetch('/health');
    dot.style.background = 'var(--success)';
    dot.style.boxShadow = '0 0 8px var(--success)';
    label.textContent = 'API Connected';
  } catch {
    dot.style.background = 'var(--error)';
    dot.style.boxShadow = '0 0 8px var(--error)';
    label.textContent = 'API Offline';
  }
}

let _healthInterval = null;
let _statsInterval = null;

function pausePolling() {
  if (_healthInterval) { clearInterval(_healthInterval); _healthInterval = null; }
  if (_statsInterval) { clearInterval(_statsInterval); _statsInterval = null; }
}
function resumePolling() {
  if (!_healthInterval) _healthInterval = setInterval(checkHealth, 60000);
  if (!_statsInterval) _statsInterval = setInterval(loadKBStats, 60000);
}

document.addEventListener('DOMContentLoaded', () => {
  checkHealth();
  loadKBStats();
  loadKBFiles();
  loadRuns();
  loadPolicies();
  loadCompanyProfile();
  resumePolling();
});
