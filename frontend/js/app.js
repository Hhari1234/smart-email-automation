/**
 * ResumeMailer — Premium Frontend Application
 */

const API_BASE = '';

// ============================================
// State
// ============================================
const state = {
  currentView: 'setup',
  recipients: [],
  settings: {},
  sendStatus: 'idle',
  pollTimer: null,
  repeatStatus: 'idle',
  repeatPollTimer: null,
};

// ============================================
// Utilities
// ============================================
function is_valid_email(email) {
  if (!email || typeof email !== 'string') return false;
  return /^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/.test(email.trim());
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function basename(p) {
  if (!p) return '';
  const s = String(p).replace(/\\/g, '/');
  const i = s.lastIndexOf('/');
  return i >= 0 ? s.slice(i + 1) : s;
}

// ============================================
// DOM References
// ============================================
const $ = (id) => document.getElementById(id);

// ============================================
// Initialization
// ============================================
document.addEventListener('DOMContentLoaded', () => {
  initNavigation();
  initAuth();
  initSetup();
  initRecipients();
  initTemplate();
  initSend();
  initRepeatSend();
  initFileUploads();
  initModals();
  loadInitialData();
  startPolling();
  initCardGlow();
});

function initAuth() {
  const btn = $('logout-btn');
  if (btn) btn.addEventListener('click', logout);
}

// ============================================
// Card Glow Effect
// ============================================
function initCardGlow() {
  document.querySelectorAll('.glass-card').forEach(card => {
    card.addEventListener('mousemove', (e) => {
      const rect = card.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 100;
      const y = ((e.clientY - rect.top) / rect.height) * 100;
      card.style.setProperty('--mouse-x', `${x}%`);
      card.style.setProperty('--mouse-y', `${y}%`);
    });
  });
}

// ============================================
// Navigation
// ============================================
function initNavigation() {
  const navItems = document.querySelectorAll('.nav-item');
  const mobileBtn = $('mobile-menu-btn');
  const sidebar = $('sidebar');

  navItems.forEach(item => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      const view = item.dataset.view;
      switchView(view);
      if (window.innerWidth <= 768) {
        sidebar.classList.remove('open');
      }
    });
  });

  if (mobileBtn) {
    mobileBtn.addEventListener('click', () => {
      sidebar.classList.toggle('open');
    });
  }

  // Close sidebar on outside click (mobile)
  document.addEventListener('click', (e) => {
    if (window.innerWidth <= 768 && sidebar.classList.contains('open')) {
      if (!sidebar.contains(e.target) && e.target !== mobileBtn) {
        sidebar.classList.remove('open');
      }
    }
  });
}

function switchView(view) {
  state.currentView = view;

  // Update nav
  document.querySelectorAll('.nav-item').forEach(item => {
    item.classList.toggle('active', item.dataset.view === view);
  });

  // Update views
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  const target = $(`view-${view}`);
  if (target) target.classList.add('active');

  // Update title
  const titles = {
    setup: 'Setup',
    recipients: 'Recipients',
    template: 'Template',
    send: 'Send Campaign',
  };
  $('page-title').textContent = titles[view] || 'ResumeMailer';
}

// ============================================
// API Helpers
// ============================================
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

function getCookie(name) {
  const prefix = `${name}=`;
  const parts = (document.cookie || '').split(';');
  for (const p of parts) {
    const c = p.trim();
    if (c.startsWith(prefix)) return decodeURIComponent(c.slice(prefix.length));
  }
  return '';
}

function buildHeaders(options) {
  const headers = { ...(options.headers || {}) };
  const method = (options.method || 'GET').toUpperCase();
  if (UNSAFE_METHODS.has(method)) {
    const csrf = getCookie('rm_csrf');
    if (csrf) headers['X-CSRF-Token'] = csrf;
  }
  return headers;
}

function handleAuthError(res) {
  if (res.status === 401) {
    // Session expired or not logged in.
    window.location.replace('/login');
    return true;
  }
  return false;
}

async function api(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const config = {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    ...options,
  };
  config.headers = buildHeaders(config);

  if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
    config.body = JSON.stringify(options.body);
  }

  const res = await fetch(url, config);
  if (handleAuthError(res)) {
    throw new Error('Not authenticated');
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json().catch(() => ({}));
}

async function apiFile(path, formData) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: buildHeaders({ method: 'POST' }),
    body: formData,
  });
  if (handleAuthError(res)) {
    throw new Error('Not authenticated');
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ============================================
// Toast Notifications
// ============================================
function showToast(message, type = 'info', duration = 4000) {
  const container = $('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;

  const icons = {
    success: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
    error: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    warning: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    info: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
  };

  toast.innerHTML = `
    ${icons[type] || icons.info}
    <span class="toast-message">${escapeHtml(message)}</span>
    <button class="toast-close" aria-label="Close">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="18" y1="6" x2="6" y2="18"/>
        <line x1="6" y1="6" x2="18" y2="18"/>
      </svg>
    </button>
  `;

  container.appendChild(toast);

  const close = () => {
    toast.classList.add('removing');
    setTimeout(() => toast.remove(), 300);
  };

  toast.querySelector('.toast-close').addEventListener('click', close);
  setTimeout(close, duration);
}

// ============================================
// Load Initial Data
// ============================================
async function loadInitialData() {
  try {
    const [settings, recipients] = await Promise.all([
      api('/api/settings'),
      api('/api/recipients'),
    ]);
    state.settings = settings;
    state.recipients = recipients.recipients || [];

    populateSetupForm(settings);
    renderRecipientsTable(state.recipients);
    updateRecipientsSummary(recipients);
  } catch (err) {
    showToast('Failed to load initial data: ' + err.message, 'error');
  }
}

// ============================================
// Setup View
// ============================================
function initSetup() {
  $('save-settings-btn').addEventListener('click', saveSettings);
}

function populateSetupForm(s) {
  $('sender-name').value = s.sender_name || '';
  $('sender-email').value = s.sender_email || '';
  $('sender-phone').value = s.sender_phone || '';
  $('sender-linkedin').value = s.sender_linkedin || '';
  $('delay-min').value = s.delay_min_seconds ?? 5;
  $('delay-max').value = s.delay_max_seconds ?? 15;
  $('max-retries').value = s.max_retries ?? 3;
  $('use-gmail-api').checked = s.use_gmail_api !== false;
  $('resume-path').value = s.resume_path || '';
  if (s.resume_path) {
    $('resume-label').textContent = basename(s.resume_path);
  }
}

async function saveSettings() {
  const btn = $('save-settings-btn');
  const btnText = btn.querySelector('.btn-text');
  const btnLoader = btn.querySelector('.btn-loader');

  btn.disabled = true;
  btnText.style.display = 'none';
  btnLoader.style.display = 'inline-block';

  try {
    const payload = {
      sender_name: $('sender-name').value,
      sender_email: $('sender-email').value,
      sender_phone: $('sender-phone').value,
      sender_linkedin: $('sender-linkedin').value,
      delay_min_seconds: parseFloat($('delay-min').value) || 5,
      delay_max_seconds: parseFloat($('delay-max').value) || 15,
      max_retries: parseInt($('max-retries').value) || 3,
      use_gmail_api: $('use-gmail-api').checked,
      resume_path: $('resume-path').value,
      extra_attachments: Array.from(document.querySelectorAll('#extra-files-list .file-tag button')).map(btn => btn.dataset.path),
    };

    await api('/api/settings', { method: 'POST', body: payload });
    state.settings = { ...state.settings, ...payload };
    showToast('Settings saved successfully', 'success');
  } catch (err) {
    showToast('Failed to save settings: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    btnText.style.display = 'inline';
    btnLoader.style.display = 'none';
  }
}

// ============================================
// Recipients View
// ============================================
function initRecipients() {
  const uploadZone = $('upload-zone');
  const fileInput = $('recipients-upload');

  // Drag and drop
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    uploadZone.addEventListener(eventName, preventDefaults, false);
  });

  function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
  }

  ['dragenter', 'dragover'].forEach(eventName => {
    uploadZone.addEventListener(eventName, () => uploadZone.classList.add('dragover'));
  });

  ['dragleave', 'drop'].forEach(eventName => {
    uploadZone.addEventListener(eventName, () => uploadZone.classList.remove('dragover'));
  });

  uploadZone.addEventListener('drop', (e) => {
    const files = e.dataTransfer.files;
    if (files.length) handleRecipientFile(files[0]);
  });

  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length) handleRecipientFile(e.target.files[0]);
  });

  $('browse-recipients-btn').addEventListener('click', () => fileInput.click());
  $('download-sample-btn').addEventListener('click', downloadSample);
  $('clear-recipients-btn').addEventListener('click', clearRecipients);
  $('recipients-search').addEventListener('input', (e) => filterRecipients(e.target.value));

  // Paste email parsing
  $('parse-emails-btn').addEventListener('click', parsePastedEmails);
  $('merge-recipients-btn').addEventListener('click', mergeParsedRecipients);
}

let parsedRecipientsCache = { valid: [], invalid: [], duplicates: [] };
const PAGE_SIZE = 100;
let currentPage = 1;
let currentViewRecipients = [];

async function parsePastedEmails() {
  const raw = $('paste-emails').value;
  if (!raw.trim()) {
    showToast('Please paste some email addresses first', 'error');
    return;
  }
  try {
    const result = await api('/api/recipients/parse', {
      method: 'POST',
      body: { raw_text: raw },
    });
    parsedRecipientsCache = result;
    $('parse-valid').textContent = `${result.valid} valid`;
    $('parse-duplicates').textContent = `${result.duplicates} duplicates`;
    $('parse-invalid').textContent = `${result.invalid} invalid`;
    $('parse-summary').style.display = 'flex';
    $('merge-recipients-btn').disabled = result.valid === 0;

    if (result.invalid > 0) {
      $('invalid-list').style.display = 'block';
      $('invalid-entries').innerHTML = result.invalid_entries.map(e => `<span class="chip chip-danger">${escapeHtml(e)}</span>`).join(' ');
    } else {
      $('invalid-list').style.display = 'none';
    }
    showToast(`Parsed ${result.valid} valid, ${result.duplicates} duplicates, ${result.invalid} invalid`, 'success');
  } catch (err) {
    showToast('Parse failed: ' + err.message, 'error');
  }
}

async function mergeParsedRecipients() {
  if (!parsedRecipientsCache.valid.length) return;
  try {
    const result = await api('/api/recipients/merge', {
      method: 'POST',
      body: { new_recipients: parsedRecipientsCache.valid },
    });
    state.recipients = result.recipients || [];
    renderRecipientsTable(state.recipients);
    updateRecipientsSummary(result);
    showToast(`Merged ${result.new_added} new recipients (${result.duplicates_removed} duplicates skipped)`, 'success');
    $('paste-emails').value = '';
    $('parse-summary').style.display = 'none';
    $('invalid-list').style.display = 'none';
    $('merge-recipients-btn').disabled = true;
    parsedRecipientsCache = { valid: [], invalid: [], duplicates: [] };
  } catch (err) {
    showToast('Merge failed: ' + err.message, 'error');
  }
}

async function handleRecipientFile(file) {
  const formData = new FormData();
  formData.append('file', file);

  try {
    showToast('Importing recipients...', 'info');
    const result = await apiFile('/api/recipients/import', formData);
    state.recipients = result.recipients || [];
    renderRecipientsTable(state.recipients);
    updateRecipientsSummary(result);
    showToast(`Imported ${result.imported} recipients (${result.valid_emails} valid emails)`, 'success');
  } catch (err) {
    showToast('Import failed: ' + err.message, 'error');
  }
}

function renderRecipientsTable(recipients) {
  const tbody = $('recipients-tbody');
  const container = $('recipients-table-container');
  const badge = $('recipient-count-badge');

  currentViewRecipients = recipients || [];
  currentPage = 1;
  _renderCurrentPage();

  if (!currentViewRecipients.length) {
    container.style.display = 'none';
    if (badge) badge.style.display = 'none';
    return;
  }
  container.style.display = 'block';
  if (badge) { badge.style.display = 'inline-flex'; badge.textContent = currentViewRecipients.length; }
}

function _renderCurrentPage() {
  const tbody = $('recipients-tbody');
  if (!currentViewRecipients.length) {
    tbody.innerHTML = '';
    return;
  }
  const total = currentViewRecipients.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (currentPage > totalPages) currentPage = totalPages;
  const start = (currentPage - 1) * PAGE_SIZE;
  const end = Math.min(total, start + PAGE_SIZE);
  const slice = currentViewRecipients.slice(start, end);

  const rowsHtml = slice.map(r => {
    const valid = is_valid_email(r.email);
    const statusBadge = valid
      ? '<span class="badge badge-success">Valid</span>'
      : '<span class="badge badge-danger">Invalid</span>';
    return `
      <tr>
        <td>${escapeHtml(r.hr_name || '-')}</td>
        <td>${escapeHtml(r.company || '-')}</td>
        <td>${escapeHtml(r.email || '-')}</td>
        <td>${escapeHtml(r.job_role || '-')}</td>
        <td>${escapeHtml(r.location || '-')}</td>
        <td>${statusBadge}</td>
      </tr>
    `;
  }).join('');

  let pager = '';
  if (totalPages > 1) {
    pager = `
      <tr class="pager-row">
        <td colspan="6" style="text-align:center; padding: 12px;">
          <button class="btn btn-ghost btn-sm" id="page-prev" ${currentPage === 1 ? 'disabled' : ''}>‹ Prev</button>
          <span style="margin: 0 12px; color: var(--text-muted);">Page ${currentPage} of ${totalPages} · ${start+1}–${end} of ${total}</span>
          <button class="btn btn-ghost btn-sm" id="page-next" ${currentPage === totalPages ? 'disabled' : ''}>Next ›</button>
        </td>
      </tr>
    `;
  }

  tbody.innerHTML = rowsHtml + pager;

  const prev = $('page-prev');
  const next = $('page-next');
  if (prev) prev.addEventListener('click', () => { currentPage--; _renderCurrentPage(); });
  if (next) next.addEventListener('click', () => { currentPage++; _renderCurrentPage(); });
}

function updateRecipientsSummary(stats) {
  const summary = $('recipients-summary');
  const badge = $('recipient-count-badge');
  if (!state.recipients.length) {
    summary.style.display = 'none';
    if (badge) badge.style.display = 'none';
    return;
  }
  summary.style.display = 'flex';
  if (badge) { badge.style.display = 'inline-flex'; badge.textContent = state.recipients.length; }

  let total = state.recipients.length;
  let valid = 0, invalid = 0, duplicates = 0, previouslySent = 0, ready = 0;
  if (stats) {
    if (typeof stats.count === 'number') total = stats.count;
    if (typeof stats.valid === 'number') valid = stats.valid;
    if (typeof stats.invalid === 'number') invalid = stats.invalid;
    if (typeof stats.duplicates === 'number') duplicates = stats.duplicates;
    if (typeof stats.previously_sent === 'number') previouslySent = stats.previously_sent;
    if (typeof stats.ready === 'number') ready = stats.ready;
  }
  if (!stats) {
    const seen = new Set();
    state.recipients.forEach(r => {
      const email = (r.email || '').toLowerCase().trim();
      if (!is_valid_email(email)) { invalid++; return; }
      valid++;
      if (seen.has(email)) { duplicates++; return; }
      seen.add(email);
      ready++;
    });
  }
  $('total-recipients').textContent = total;
  $('valid-recipients').textContent = valid;
  $('invalid-recipients').textContent = invalid;
  $('duplicate-recipients').textContent = duplicates;
  $('previously-sent-recipients').textContent = previouslySent;
  $('ready-recipients').textContent = ready;
}

function filterRecipients(query) {
  const q = query.toLowerCase();
  const filtered = state.recipients.filter(r =>
    Object.values(r).some(v => String(v).toLowerCase().includes(q))
  );
  renderRecipientsTable(filtered);
}

function clearRecipients() {
  state.recipients = [];
  renderRecipientsTable([]);
  updateRecipientsSummary(0, 0);
  showToast('Recipients cleared', 'info');
}

async function downloadSample() {
  try {
    const res = await fetch('/api/files/sample', { credentials: 'same-origin' });
    if (res.status === 401) { window.location.replace('/login'); return; }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'recipients_sample.xlsx';
    a.click();
    URL.revokeObjectURL(url);
    showToast('Sample template downloaded', 'success');
  } catch (err) {
    showToast('Download failed: ' + err.message, 'error');
  }
}

// ============================================
// Logout
// ============================================
async function logout() {
  try {
    await fetch('/api/auth/logout', {
      method: 'POST',
      credentials: 'same-origin',
      headers: buildHeaders({ method: 'POST' }),
    });
  } catch (_) { /* proceed to redirect anyway */ }
  window.location.replace('/login');
}

// ============================================
// Template View
// ============================================
function initTemplate() {
  const placeholders = ['hr_name', 'company', 'job_role', 'location', 'your_name', 'your_email', 'your_phone', 'your_linkedin'];
  const chipsContainer = $('placeholder-chips');
  chipsContainer.innerHTML = placeholders.map(p =>
    `<span class="chip" data-ph="${p}">{{${p}}}</span>`
  ).join('');

  const body = $('email-body');
  chipsContainer.addEventListener('click', (e) => {
    if (e.target.classList.contains('chip')) {
      const ph = e.target.dataset.ph;
      body.setRangeText(`{{${ph}}}`, body.selectionStart, body.selectionEnd, 'end');
      body.focus();
    }
  });

  $('insert-fallback-btn').addEventListener('click', () => {
    const fallback = $('fallback-input').value.trim();
    if (!fallback) {
      showToast('Enter fallback text first', 'error');
      return;
    }
    const sel = body.value.substring(body.selectionStart, body.selectionEnd);
    if (sel && sel.startsWith('{{') && sel.endsWith('}}')) {
      const ph = sel.slice(2, -2).split('|')[0].trim();
      body.setRangeText(`{{${ph}|${fallback}}}`, body.selectionStart, body.selectionEnd, 'end');
    } else {
      body.setRangeText(`{{name|${fallback}}}`, body.selectionStart, body.selectionEnd, 'end');
    }
    body.focus();
    showToast('Fallback placeholder inserted', 'success');
  });

  $('preview-btn').addEventListener('click', generatePreview);
  $('send-test-btn').addEventListener('click', sendTestEmail);
  $('preview-desktop-btn').addEventListener('click', () => setPreviewMode('desktop'));
  $('preview-mobile-btn').addEventListener('click', () => setPreviewMode('mobile'));

  // Load default template
  if (!body.value.trim()) {
    body.value = `Dear {{hr_name}},\n\nI hope you're doing well. I'm reaching out to apply for the {{job_role}} position at {{company}}.\n\nI've attached my resume for your review and would be grateful for the opportunity to discuss how I could contribute to your team.\n\nThank you for your time and consideration.`;
  }
  if (!$('email-signature').value.trim()) {
    $('email-signature').value = `<br><br>Best regards,<br><b>{{your_name}}</b><br>{{your_phone}} | {{your_email}}<br>{{your_linkedin}}`;
  }
  if (!$('email-subject').value.trim()) {
    $('email-subject').value = 'Application for {{job_role}} at {{company}}';
  }
}

function setPreviewMode(mode) {
  const frame = $('preview-frame');
  if (mode === 'mobile') {
    frame.style.maxWidth = '375px';
    frame.style.margin = '0 auto';
  } else {
    frame.style.maxWidth = '680px';
    frame.style.margin = '0 auto';
  }
}

async function generatePreview() {
  const subject = $('email-subject').value;
  const body = $('email-body').value;
  const signature = $('email-signature').value;
  const context = buildContext();

  try {
    const result = await api('/api/template/preview', {
      method: 'POST',
      body: { subject, body, signature, context },
    });

    const preview = $('preview-email');
    preview.innerHTML = `
      <div style="margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px solid var(--border);">
        <strong style="color: var(--text-muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em;">Subject</strong>
        <p style="margin-top: 4px; font-weight: 600;">${escapeHtml(result.subject)}</p>
      </div>
      <div>${result.full_html}</div>
    `;
    showToast('Preview generated', 'success');
  } catch (err) {
    showToast('Preview failed: ' + err.message, 'error');
  }
}

async function sendTestEmail() {
  const subject = $('email-subject').value;
  const body = $('email-body').value;
  const signature = $('email-signature').value;
  const toEmail = state.settings.sender_email || $('sender-email').value;

  if (!to_email_valid(toEmail)) {
    showToast('Please enter a valid sender email in Setup first', 'error');
    return;
  }

  try {
    showToast('Sending test email...', 'info');
    const resumePath = state.settings.resume_path || '';
    const attachments = resumePath ? [resumePath] : [];
    const result = await api('/api/email/test', {
      method: 'POST',
      body: {
        subject,
        body,
        signature,
        to_email: toEmail,
        context: buildContext(),
        attachments,
      },
    });
    showToast(`Test email sent via ${result.backend}`, 'success');
  } catch (err) {
    showToast('Test email failed: ' + err.message, 'error');
  }
}

function buildContext() {
  const first = state.recipients[0] || {};
  return {
    hr_name: first.hr_name || 'Jane Doe',
    company: first.company || 'Example Corp',
    job_role: first.job_role || 'Software Engineer',
    location: first.location || 'Bengaluru',
    your_name: $('sender-name').value || state.settings.sender_name || '',
    your_email: $('sender-email').value || state.settings.sender_email || '',
    your_phone: $('sender-phone').value || state.settings.sender_phone || '',
    your_linkedin: $('sender-linkedin').value || state.settings.sender_linkedin || '',
  };
}

function to_email_valid(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

// ============================================
// Send View
// ============================================
function initSend() {
  $('start-send-btn').addEventListener('click', startSend);
  $('pause-send-btn').addEventListener('click', pauseSend);
  $('resume-send-btn').addEventListener('click', resumeSend);
  $('stop-send-btn').addEventListener('click', stopSend);
  $('clear-log-btn').addEventListener('click', () => {
    $('log-box').innerHTML = '<div class="log-empty">Waiting to start...</div>';
  });
}

function initRepeatSend() {
  const emailInput = $('repeat-email');
  const countInput = $('repeat-count');
  const delayInput = $('repeat-delay');
  const summary = $('repeat-summary');
  const sendBtn = $('repeat-send-btn');
  const sendBtnText = $('repeat-send-btn-text');
  const stopBtn = $('repeat-stop-btn');
  const clearBtn = $('clear-repeat-log-btn');

  function updateSummary() {
    const email = (emailInput.value || '').trim();
    const count = Math.max(1, Math.min(20, parseInt(countInput.value) || 1));
    const delay = Math.max(1, Math.min(60, parseInt(delayInput.value) || 5));
    if (count === 1) {
      summary.textContent = email
        ? `This email will be sent 1 time to ${email}.`
        : 'This email will be sent 1 time.';
      sendBtnText.textContent = 'Send Email';
    } else {
      summary.textContent = email
        ? `This email will be sent ${count} times to ${email}. Delay: ${delay} seconds between emails.`
        : `This email will be sent ${count} times. Delay: ${delay} seconds between emails.`;
      sendBtnText.textContent = `Send Email ${count} Times`;
    }
  }

  [emailInput, countInput, delayInput].forEach(el => {
    if (el) el.addEventListener('input', updateSummary);
    if (el) el.addEventListener('change', updateSummary);
  });

  updateSummary();

  sendBtn.addEventListener('click', async () => {
    const email = (emailInput.value || '').trim();
    const count = Math.max(1, Math.min(20, parseInt(countInput.value) || 1));
    const delay = Math.max(1, Math.min(60, parseInt(delayInput.value) || 5));

    if (!email) {
      showToast('Please enter a recipient email address', 'error');
      return;
    }

    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      showToast('Please enter a valid email address', 'error');
      return;
    }

    if (count > 1) {
      const confirmed = await showConfirm(
        `You are about to send this email ${count} times to ${email}. Continue?`,
        `Send ${count} Emails`
      );
      if (!confirmed) return;
    }

    const subject = $('email-subject').value;
    const body = $('email-body').value;
    const signature = $('email-signature').value;
    const resumePath = state.settings.resume_path || '';
    const attachments = resumePath ? [resumePath] : [];

    try {
      await api('/api/repeat-send/start', {
        method: 'POST',
        body: {
          to_email: email,
          subject,
          body,
          signature,
          count,
          delay_seconds: delay,
          attachments,
        },
      });
      updateRepeatSendUI('running');
      startRepeatPolling();
      showToast('Repeat send started', 'success');
    } catch (err) {
      showToast('Failed to start repeat send: ' + err.message, 'error');
    }
  });

  stopBtn.addEventListener('click', async () => {
    try {
      await api('/api/repeat-send/stop', { method: 'POST' });
      updateRepeatSendUI('stopped');
      showToast('Repeat send stopped', 'warning');
    } catch (err) {
      showToast('Stop failed: ' + err.message, 'error');
    }
  });

  clearBtn.addEventListener('click', () => {
    $('repeat-log-box').innerHTML = '<div class="log-empty">Waiting to start...</div>';
  });
}

function updateRepeatSendUI(status) {
  state.repeatStatus = status;
  const isRunning = status === 'running';
  const isStopped = status === 'stopped';
  const isIdle = status === 'idle' || isStopped;

  $('repeat-send-btn').disabled = !isIdle;
  $('repeat-stop-btn').disabled = isIdle;
  $('repeat-email').disabled = !isIdle;
  $('repeat-count').disabled = !isIdle;
  $('repeat-delay').disabled = !isIdle;

  if (isRunning) {
    $('repeat-progress-container').style.display = 'flex';
    $('repeat-log-container').style.display = 'block';
  }
}

function startRepeatPolling() {
  if (state.repeatPollTimer) clearInterval(state.repeatPollTimer);
  state.repeatPollTimer = setInterval(pollRepeatStatus, 500);
}

async function pollRepeatStatus() {
  try {
    const data = await api('/api/repeat-send/status');
    const { repeat_status, progress, logs } = data;

    if (progress) {
      const total = progress.total || 1;
      const current = progress.current || 0;
      const pct = total > 0 ? Math.round((current / total) * 100) : 0;
      $('repeat-progress-fill').style.width = `${pct}%`;
      $('repeat-progress-text').textContent = `${current}/${total}`;
    }

    if (repeat_status && repeat_status !== state.repeatStatus) {
      const isDone = ['completed', 'stopped', 'error'].includes(repeat_status);
      updateRepeatSendUI(isDone ? 'idle' : repeat_status);
      if (isDone && state.repeatPollTimer) {
        clearInterval(state.repeatPollTimer);
        state.repeatPollTimer = null;
      }
    }

    if (logs && logs.length) {
      const logBox = $('repeat-log-box');
      logBox.innerHTML = logs.slice(-50).map(line => `<div class="log-line">${escapeHtml(line)}</div>`).join('');
      logBox.scrollTop = logBox.scrollHeight;
    }
  } catch (err) {
    // Silently ignore poll errors
  }
}

function showConfirm(message, confirmLabel) {
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal-card">
        <p class="modal-message">${escapeHtml(message)}</p>
        <div class="modal-actions">
          <button class="btn btn-secondary" id="modal-cancel">Cancel</button>
          <button class="btn btn-primary" id="modal-confirm">${escapeHtml(confirmLabel || 'Confirm')}</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    overlay.querySelector('#modal-cancel').addEventListener('click', () => {
      overlay.remove();
      resolve(false);
    });
    overlay.querySelector('#modal-confirm').addEventListener('click', () => {
      overlay.remove();
      resolve(true);
    });
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) {
        overlay.remove();
        resolve(false);
      }
    });
  });
}

async function startSend() {
  const subject = $('email-subject').value;
  const body = $('email-body').value;
  const signature = $('email-signature').value;

  if (!state.recipients.length) {
    showToast('No recipients loaded. Import recipients first.', 'error');
    return;
  }

  const validCount = state.recipients.filter(r => is_valid_email(r.email)).length;
  const invalidCount = state.recipients.length - validCount;

  // Show review modal
  $('review-total').textContent = state.recipients.length;
  $('review-valid').textContent = validCount;
  $('review-invalid').textContent = invalidCount;
  $('review-subject').textContent = subject || '(no subject)';

  const attachments = collectAttachments();
  $('review-attachments').textContent = attachments.length ? attachments.map(a => a.split('/').pop()).join(', ') : 'None';

  const delayMin = $('delay-min').value || '5';
  const delayMax = $('delay-max').value || '15';
  $('review-delay').textContent = `${delayMin}–${delayMax}s`;
  $('review-retries').textContent = $('max-retries').value || '3';

  showModal('campaign-review-modal');

  $('review-confirm-btn').onclick = async () => {
    hideModal('campaign-review-modal');
    try {
      await api('/api/send/start', {
        method: 'POST',
        body: { subject, body, signature, attachments },
      });
      updateSendUI('running');
      showToast('Campaign started', 'success');
    } catch (err) {
      showToast('Failed to start: ' + err.message, 'error');
    }
  };

  $('review-cancel-btn').onclick = () => hideModal('campaign-review-modal');
  $('close-campaign-review').onclick = () => hideModal('campaign-review-modal');
}

async function pauseSend() {
  try {
    await api('/api/send/pause', { method: 'POST' });
    updateSendUI('paused');
    showToast('Campaign paused', 'info');
  } catch (err) {
    showToast('Pause failed: ' + err.message, 'error');
  }
}

async function resumeSend() {
  try {
    await api('/api/send/resume', { method: 'POST' });
    updateSendUI('running');
    showToast('Campaign resumed', 'info');
  } catch (err) {
    showToast('Resume failed: ' + err.message, 'error');
  }
}

async function stopSend() {
  try {
    await api('/api/send/stop', { method: 'POST' });
    updateSendUI('idle');
    showToast('Campaign stopped', 'warning');
  } catch (err) {
    showToast('Stop failed: ' + err.message, 'error');
  }
}

function updateSendUI(status) {
  state.sendStatus = status;
  const isRunning = status === 'running';
  const isPaused = status === 'paused';
  const isIdle = status === 'idle';

  $('start-send-btn').disabled = !isIdle;
  $('pause-send-btn').disabled = !isRunning;
  $('resume-send-btn').disabled = !isPaused;
  $('stop-send-btn').disabled = isIdle;

  const badge = $('send-status-badge');
  const badges = {
    idle: '<span class="badge badge-info">Idle</span>',
    running: '<span class="badge badge-success">Running</span>',
    paused: '<span class="badge badge-warning">Paused</span>',
  };
  badge.innerHTML = badges[status] || badges.idle;
}

// ============================================
// Modal Helpers
// ============================================
function showModal(id) {
  const el = $(id);
  if (el) { el.style.display = 'flex'; }
}

function hideModal(id) {
  const el = $(id);
  if (el) { el.style.display = 'none'; }
}

function collectAttachments() {
  const files = [];
  const resume = state.settings.resume_path || '';
  if (resume) files.push(resume);
  const extraTags = document.querySelectorAll('#extra-files-list .file-tag button');
  extraTags.forEach(btn => { if (btn.dataset.path) files.push(btn.dataset.path); });
  return files;
}

// ============================================
// Template Library
// ============================================
async function loadTemplateLibrary() {
  try {
    const data = await api('/api/templates');
    const list = $('template-list');
    if (!data.templates || !data.templates.length) {
      list.innerHTML = '<p class="empty-hint">No saved templates yet.</p>';
      return;
    }
    list.innerHTML = data.templates.map(t => `
      <div class="template-item">
        <div class="template-info">
          <strong>${escapeHtml(t.name)}</strong>
          <p class="form-hint">${escapeHtml(t.subject || 'No subject')}</p>
        </div>
        <div class="template-actions">
          <button class="btn btn-secondary btn-sm" onclick="applyTemplate(${t.id})">Use</button>
          <button class="btn btn-ghost btn-sm" onclick="deleteTemplate(${t.id})">Delete</button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    showToast('Failed to load templates: ' + err.message, 'error');
  }
}

async function applyTemplate(templateId) {
  try {
    const tpl = await api(`/api/templates/${templateId}`);
    $('email-subject').value = tpl.subject;
    $('email-body').value = tpl.body;
    $('email-signature').value = tpl.signature;
    hideModal('template-library-modal');
    showToast('Template applied', 'success');
  } catch (err) {
    showToast('Failed to load template: ' + err.message, 'error');
  }
}

async function saveCurrentAsTemplate() {
  const name = prompt('Template name:');
  if (!name) return;
  try {
    await api('/api/templates', {
      method: 'POST',
      body: {
        name,
        subject: $('email-subject').value,
        body: $('email-body').value,
        signature: $('email-signature').value,
      },
    });
    showToast('Template saved', 'success');
    loadTemplateLibrary();
  } catch (err) {
    showToast('Failed to save template: ' + err.message, 'error');
  }
}

async function deleteTemplate(templateId) {
  if (!confirm('Delete this template?')) return;
  try {
    await api(`/api/templates/${templateId}`, { method: 'DELETE' });
    showToast('Template deleted', 'info');
    loadTemplateLibrary();
  } catch (err) {
    showToast('Failed to delete template: ' + err.message, 'error');
  }
}

// ============================================
// Drafts
// ============================================
async function loadDrafts() {
  try {
    const data = await api('/api/drafts');
    const list = $('draft-list');
    if (!data.drafts || !data.drafts.length) {
      list.innerHTML = '<p class="empty-hint">No saved drafts yet.</p>';
      return;
    }
    list.innerHTML = data.drafts.map(d => `
      <div class="template-item">
        <div class="template-info">
          <strong>${escapeHtml(d.name || 'Untitled Draft')}</strong>
          <p class="form-hint">${escapeHtml(d.subject || 'No subject')}</p>
          <p class="form-hint">${d.recipients ? d.recipients.length : 0} recipients</p>
        </div>
        <div class="template-actions">
          <button class="btn btn-secondary btn-sm" onclick="loadDraft(${d.id})">Open</button>
          <button class="btn btn-ghost btn-sm" onclick="deleteDraft(${d.id})">Delete</button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    showToast('Failed to load drafts: ' + err.message, 'error');
  }
}

async function loadDraft(draftId) {
  try {
    const d = await api(`/api/drafts/${draftId}`);
    $('email-subject').value = d.subject;
    $('email-body').value = d.body;
    $('email-signature').value = d.signature;
    if (d.recipients && d.recipients.length) {
      state.recipients = d.recipients;
      renderRecipientsTable(state.recipients);
      updateRecipientsSummary(null);
    }
    hideModal('drafts-modal');
    showToast('Draft loaded', 'success');
  } catch (err) {
    showToast('Failed to load draft: ' + err.message, 'error');
  }
}

async function saveCurrentAsDraft() {
  const name = prompt('Draft name:');
  if (!name) return;
  try {
    await api('/api/drafts', {
      method: 'POST',
      body: {
        name,
        subject: $('email-subject').value,
        body: $('email-body').value,
        signature: $('email-signature').value,
        recipients: state.recipients,
        attachments: collectAttachments(),
        settings: state.settings,
      },
    });
    showToast('Draft saved', 'success');
    loadDrafts();
  } catch (err) {
    showToast('Failed to save draft: ' + err.message, 'error');
  }
}

async function deleteDraft(draftId) {
  if (!confirm('Delete this draft?')) return;
  try {
    await api(`/api/drafts/${draftId}`, { method: 'DELETE' });
    showToast('Draft deleted', 'info');
    loadDrafts();
  } catch (err) {
    showToast('Failed to delete draft: ' + err.message, 'error');
  }
}

// ============================================
// Campaign History
// ============================================
async function loadCampaignHistory() {
  try {
    const data = await api('/api/campaigns');
    const list = $('campaign-list');
    if (!data.campaigns || !data.campaigns.length) {
      list.innerHTML = '<p class="empty-hint">No campaigns yet.</p>';
      return;
    }
    list.innerHTML = data.campaigns.map(c => `
      <div class="template-item">
        <div class="template-info">
          <strong>Campaign #${c.id}</strong>
          <p class="form-hint">${escapeHtml(c.subject || 'No subject')}</p>
          <p class="form-hint">Sent: ${c.sent_count} | Failed: ${c.failed_count} | Skipped: ${c.skipped_count} | Status: ${c.status}</p>
          <p class="form-hint">${new Date(c.created_at).toLocaleString()}</p>
        </div>
        <div class="template-actions">
          <button class="btn btn-secondary btn-sm" onclick="viewCampaignRecipients(${c.id})">View Recipients</button>
          <button class="btn btn-ghost btn-sm" onclick="deleteCampaign(${c.id})">Delete</button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    showToast('Failed to load campaigns: ' + err.message, 'error');
  }
}

async function viewCampaignRecipients(campaignId) {
  try {
    const data = await api(`/api/campaigns/${campaignId}/recipients`);
    const rows = data.recipients || [];
    if (!rows.length) {
      showToast('No recipients for this campaign', 'info');
      return;
    }
    const csvContent = 'data:text/csv;charset=utf-8,' + encodeURIComponent(
      'Email,HR Name,Company,Job Role,Location,Status,Error,Timestamp\n' +
      rows.map(r => `"${r.email}","${r.hr_name}","${r.company}","${r.job_role}","${r.location}","${r.status}","${r.error}","${r.timestamp}"`).join('\n')
    );
    const a = document.createElement('a');
    a.href = csvContent;
    a.download = `campaign_${campaignId}_recipients.csv`;
    a.click();
    showToast('Recipients exported', 'success');
  } catch (err) {
    showToast('Failed to load recipients: ' + err.message, 'error');
  }
}

async function deleteCampaign(campaignId) {
  if (!confirm('Delete this campaign?')) return;
  try {
    await api(`/api/campaigns/${campaignId}`, { method: 'DELETE' });
    showToast('Campaign deleted', 'info');
    loadCampaignHistory();
  } catch (err) {
    showToast('Failed to delete campaign: ' + err.message, 'error');
  }
}

// ============================================
// Polling
// ============================================
function startPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(pollStatus, 500);
}

async function pollStatus() {
  try {
    const data = await api('/api/send/status');
    const { worker_status, progress, logs } = data;

    // Update stats
    if (progress) {
      $('stat-sent').textContent = progress.sent || 0;
      $('stat-failed').textContent = progress.failed || 0;
      $('stat-skipped').textContent = progress.skipped || 0;
      const remaining = (progress.total || 0) - (progress.sent || 0) - (progress.failed || 0) - (progress.skipped || 0);
      $('stat-remaining').textContent = remaining;

      // Progress bar
      const total = progress.total || 1;
      const done = (progress.sent || 0) + (progress.failed || 0) + (progress.skipped || 0);
      const pct = Math.round((done / total) * 100);
      $('progress-fill').style.width = `${pct}%`;
      $('progress-text').textContent = `${pct}%`;
    }

    // Update status
    if (worker_status && worker_status !== state.sendStatus) {
      updateSendUI(worker_status);
    }

    // Update logs
    if (logs && logs.length) {
      const logBox = $('log-box');
      const newLogs = logs.slice(-50);
      logBox.innerHTML = newLogs.map(line => `<div class="log-line">${escapeHtml(line)}</div>`).join('');
      logBox.scrollTop = logBox.scrollHeight;
    }
  } catch (err) {
    // Silently ignore poll errors
  }
}

// ============================================
// Modals Initialization
// ============================================
function initModals() {
  // Template library
  const tplBtn = document.createElement('button');
  tplBtn.className = 'btn btn-secondary';
  tplBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/></svg> Templates';
  tplBtn.addEventListener('click', () => { loadTemplateLibrary(); showModal('template-library-modal'); });
  const templateHeader = document.querySelector('#view-template .card-header');
  if (templateHeader) templateHeader.appendChild(tplBtn);

  $('save-current-template-btn').addEventListener('click', saveCurrentAsTemplate);
  $('close-template-library').addEventListener('click', () => hideModal('template-library-modal'));

  // Drafts
  const draftBtn = document.createElement('button');
  draftBtn.className = 'btn btn-secondary';
  draftBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/></svg> Drafts';
  draftBtn.addEventListener('click', () => { loadDrafts(); showModal('drafts-modal'); });
  const sendHeader = document.querySelector('#view-send .card-header');
  if (sendHeader) sendHeader.appendChild(draftBtn);

  $('save-draft-btn').addEventListener('click', saveCurrentAsDraft);
  $('close-drafts-modal').addEventListener('click', () => hideModal('drafts-modal'));

  // Campaign history
  const historyBtn = document.createElement('button');
  historyBtn.className = 'btn btn-ghost btn-sm';
  historyBtn.textContent = 'History';
  historyBtn.addEventListener('click', () => { loadCampaignHistory(); showModal('campaign-history-modal'); });
  const topBarActions = document.querySelector('.top-bar-actions');
  if (topBarActions) topBarActions.appendChild(historyBtn);

  $('close-campaign-history').addEventListener('click', () => hideModal('campaign-history-modal'));
}

// ============================================
// File Uploads (Setup)
// ============================================
function initFileUploads() {
  const resumeInput = $('resume-upload');
  const extraInput = $('extra-upload');

  if (resumeInput) {
    resumeInput.addEventListener('change', async (e) => {
      if (e.target.files.length) {
        const file = e.target.files[0];
        try {
          const formData = new FormData();
          formData.append('file', file);
          const result = await apiFile('/api/files/upload', formData);
          $('resume-path').value = result.path;
          $('resume-label').textContent = file.name;
          showToast('Resume uploaded', 'success');
        } catch (err) {
          showToast('Upload failed: ' + err.message, 'error');
        }
      }
    });
  }

  if (extraInput) {
    extraInput.addEventListener('change', async (e) => {
      if (e.target.files.length) {
        const list = $('extra-files-list');
        for (const file of e.target.files) {
          try {
            const formData = new FormData();
            formData.append('file', file);
            const result = await apiFile('/api/files/upload', formData);
            const tag = document.createElement('span');
            tag.className = 'file-tag';
            tag.innerHTML = `${escapeHtml(file.name)} <button data-path="${result.path}" aria-label="Remove"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>`;
            tag.querySelector('button').addEventListener('click', () => tag.remove());
            list.appendChild(tag);
            showToast(`Uploaded ${file.name}`, 'success');
          } catch (err) {
            showToast('Upload failed: ' + err.message, 'error');
          }
        }
      }
    });
  }
}
