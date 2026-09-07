-- D1 Schema Migration for Smart Email Automation
-- Version: 001_initial_schema

-- Users table for authentication
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    last_login_at TEXT
);

-- Templates table for email templates
CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    signature TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT
);

-- Drafts table for saved drafts
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    signature TEXT NOT NULL,
    recipients_json TEXT NOT NULL,
    attachments_json TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT
);

-- Campaigns table for email campaigns
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    signature TEXT NOT NULL,
    attachments_json TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    total_recipients INTEGER DEFAULT 0,
    sent_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'draft',
    created_at TEXT,
    updated_at TEXT
);

-- Campaign recipients table
CREATE TABLE IF NOT EXISTS campaign_recipients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    hr_name TEXT,
    company TEXT,
    job_role TEXT,
    location TEXT,
    status TEXT DEFAULT 'pending',
    error TEXT,
    timestamp TEXT,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

-- Sent emails tracking table
CREATE TABLE IF NOT EXISTS sent_emails (
    email TEXT PRIMARY KEY,
    hr_name TEXT,
    company TEXT,
    job_role TEXT,
    status TEXT,
    attempts INTEGER DEFAULT 0,
    error TEXT,
    timestamp TEXT
);

-- Indexes for user isolation
CREATE INDEX IF NOT EXISTS idx_templates_user_id ON templates(user_id);
CREATE INDEX IF NOT EXISTS idx_drafts_user_id ON drafts(user_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_user_id ON campaigns(user_id);
CREATE INDEX IF NOT EXISTS idx_campaign_recipients_campaign_id ON campaign_recipients(campaign_id);
CREATE INDEX IF NOT EXISTS idx_sent_emails_email ON sent_emails(email);
