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

function Path(p) {
  try {
    const url = new URL(p, window.location.origin);
    return { name: url.pathname.split('/').pop() || p };
  } catch {
    return { name: p.split('/').pop() || p };
  }
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
  initSetup();
  initRecipients();
  initTemplate();
  initSend();
  initFileUploads();
  loadInitialData();
  startPolling();
  initCardGlow();
});

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
async function api(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const config = {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  };

  if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
    config.body = JSON.stringify(options.body);
  }

  const res = await fetch(url, config);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json().catch(() => ({}));
}

async function apiFile(path, formData) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    body: formData,
  });
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
    updateRecipientsSummary();
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
    $('resume-label').textContent = Path(s.resume_path).name;
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
}

async function handleRecipientFile(file) {
  const formData = new FormData();
  formData.append('file', file);

  try {
    showToast('Importing recipients...', 'info');
    const result = await apiFile('/api/recipients/import', formData);
    state.recipients = result.recipients || [];
    renderRecipientsTable(state.recipients);
    updateRecipientsSummary(result.imported, result.valid_emails);
    showToast(`Imported ${result.imported} recipients (${result.valid_emails} valid emails)`, 'success');
  } catch (err) {
    showToast('Import failed: ' + err.message, 'error');
  }
}

function renderRecipientsTable(recipients) {
  const tbody = $('recipients-tbody');
  const container = $('recipients-table-container');

  if (!recipients.length) {
    container.style.display = 'none';
    return;
  }

  container.style.display = 'block';
  tbody.innerHTML = recipients.map(r => {
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
}

function updateRecipientsSummary(total, valid) {
  const summary = $('recipients-summary');
  if (!state.recipients.length) {
    summary.style.display = 'none';
    return;
  }
  summary.style.display = 'flex';
  const totalCount = total ?? state.recipients.length;
  const validCount = valid ?? state.recipients.filter(r => is_valid_email(r.email)).length;
  $('total-recipients').textContent = totalCount;
  $('valid-recipients').textContent = validCount;
  $('invalid-recipients').textContent = totalCount - validCount;
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
    const res = await fetch('/api/files/sample');
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

async function startSend() {
  const subject = $('email-subject').value;
  const body = $('email-body').value;
  const signature = $('email-signature').value;

  if (!state.recipients.length) {
    showToast('No recipients loaded. Import recipients first.', 'error');
    return;
  }

  try {
    await api('/api/send/start', {
      method: 'POST',
      body: { subject, body, signature, attachments: [] },
    });
    updateSendUI('running');
    showToast('Campaign started', 'success');
  } catch (err) {
    showToast('Failed to start: ' + err.message, 'error');
  }
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
