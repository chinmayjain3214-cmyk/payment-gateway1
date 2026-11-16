-- Tables used by the agent and the human approval workflow.
-- Separate from schema.sql so the two files never clash.

-- Every step the agent takes: tool calls, results, retries, errors
CREATE TABLE IF NOT EXISTS agent_log (
    id SERIAL PRIMARY KEY,
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    step VARCHAR(100) NOT NULL,
    detail JSONB
);

-- One row per invoice the agent has checked. A human approves or rejects it here.
CREATE TABLE IF NOT EXISTS approval_requests (
    id SERIAL PRIMARY KEY,
    file_name VARCHAR(255) NOT NULL,
    recommendation VARCHAR(30) NOT NULL,
    summary TEXT,
    review_reason TEXT,
    status VARCHAR(20) DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    decided_by VARCHAR(100),
    decided_at TIMESTAMP,
    decision_note TEXT
);


-- People who can log in to the app. Passwords are stored as salted hashes, never as plain text.
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    full_name VARCHAR(100),
    role VARCHAR(20) NOT NULL CHECK (role IN ('vendor', 'approver', 'admin')),
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Payment schedules. One row per approved invoice that is queued for payout.
CREATE TABLE IF NOT EXISTS payment_schedules (
    id SERIAL PRIMARY KEY,
    approval_request_id INT NOT NULL REFERENCES approval_requests(id),
    vendor_name VARCHAR(255),
    invoice_number VARCHAR(100),
    department_id VARCHAR(50),
    invoice_amount NUMERIC(14, 2) NOT NULL,
    scheduled_payment_date DATE NOT NULL,
    payment_status VARCHAR(20) DEFAULT 'SCHEDULED'
        CHECK (payment_status IN ('SCHEDULED', 'PAID', 'CANCELLED')),
    payment_batch_id VARCHAR(50),
    paid_at TIMESTAMP,
    paid_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (approval_request_id)
);

CREATE INDEX IF NOT EXISTS payment_schedules_status_date_idx
    ON payment_schedules (payment_status, scheduled_payment_date);

-- Vendor-facing clarification message. NULL means no vendor action needed.
ALTER TABLE approval_requests
    ADD COLUMN IF NOT EXISTS vendor_message TEXT;

-- Index so the vendor page can quickly fetch "my" submissions.
CREATE INDEX IF NOT EXISTS approval_requests_file_name_idx
    ON approval_requests (file_name);

-- Expand allowed application roles for multi-level approvals.
-- Safe to rerun; preserves existing user records.

ALTER TABLE users
    DROP CONSTRAINT IF EXISTS users_role_check;

ALTER TABLE users
    ADD CONSTRAINT users_role_check
    CHECK (
        role IN (
            'vendor',
            'procurement_officer',
            'department_head',
            'finance_officer',
            'final_approver',
            'approver',
            'admin'
        )
    );
