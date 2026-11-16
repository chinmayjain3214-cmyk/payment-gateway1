# Autonomous Accounts Payable & Vendor Invoice Agent

**JKLU AI Buildathon 2026 — Problem Statement 09**

An AI-assisted accounts payable system that automates invoice processing, validates invoices against purchase orders and goods receipts, identifies discrepancies, and routes decisions through a controlled human approval workflow.

## Overview

The project provides an intelligent invoice-processing workflow combining AI-based document understanding with deterministic financial validations and human oversight.

Instead of relying entirely on AI for financial decisions, the system uses rule-based checks for critical validations and requires human approval before an invoice can proceed to payment scheduling.

## Key Features

### 1. Invoice Processing
- Upload and extract invoice information.
- Identify important invoice fields and line items.
- Detect duplicate invoice submissions.
- Maintain extracted invoice information for subsequent checks.

### 2. Three-Way Matching
Compare invoice information against:
- Purchase Orders (POs).
- Goods Receipt Notes (GRNs).
- Vendor records.

Identify issues such as quantity mismatches, price discrepancies, vendor mismatches, and missing goods receipts.

### 3. Financial and Compliance Validation
- Invoice arithmetic and line-item checks.
- GST rate validation.
- Purchase order quantity and price checks.
- Budget validation.
- Duplicate invoice detection.

### 4. AI Agent
The AI agent assists with invoice analysis, discrepancy explanations, and workflow decisions. Deterministic checks provide an additional validation layer, so AI output alone does not authorize payment.

### 5. Human-in-the-Loop Approval
A sequential three-stage approval process:
1. Department Head
2. Finance Officer
3. Final Approver

Invoices requiring review can be routed through the approval workflow.

### 6. Vendor Clarification
The system supports clarification requests when invoice information requires additional vendor input. Vendors can view and acknowledge clarification messages.

### 7. Payment Scheduling and Tracking
- Schedule payments for approved invoices.
- Restrict payment operations to authorized Finance Officers and Admin users.
- Track scheduled, paid, and cancelled payment statuses.
- Prevent duplicate scheduling.

**Note:** Payment scheduling and tracking are implemented; the application does not directly transfer money.

### 8. Audit Trail
Maintain structured records of invoice processing and workflow events for traceability.

## Technology Stack

- **Language:** Python
- **Frontend:** Streamlit
- **Database:** PostgreSQL
- **AI:** Google Gemini API
- **Testing:** Pytest

## Project Setup

### Prerequisites

- Python 3.10 or later
- PostgreSQL
- Google Gemini API key

### 1. Clone the repository

```bash
git clone https://github.com/KARAN-2007/invoice-agent.git
cd invoice-agent
```

### 2. Create a virtual environment

Windows:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a local `.env` file containing the Gemini API key and PostgreSQL connection settings required by the application.

Use the variable names expected by the project's database and AI configuration modules.

Never commit `.env` or expose API keys in the repository.

### 5. Initialize the database

Create an empty PostgreSQL database and configure its connection.

Run:

```bash
python setup_agent_tables.py
```

This initializes the core schema, agent tables, and approval workflow tables.

### 6. Create approval accounts

Run:

```bash
python create_approval_accounts.py
```

Follow the prompts to configure the Department Head and Finance Officer accounts. Configure the final approver and administrator accounts according to the project's authentication setup.

### 7. Launch the application

```bash
streamlit run app.py
```

## Running Tests

Run the automated test suite:

```bash
python -m pytest -q
```

The project has passed **65 automated tests** in the development environment.

## Demonstration Scenarios

The `demo_test_invoices/` directory contains nine demonstration invoices covering:

| Scenario | Expected validation |
|---|---|
| Clean match | Invoice passes matching checks |
| Quantity mismatch | Quantity discrepancy |
| Price mismatch | Unit price discrepancy |
| Wrong vendor | Vendor mismatch |
| Wrong GST | GST rate mismatch |
| Missing GRN | Missing goods receipt |
| Partial receipt | GRN quantity shortage |
| Budget exceeded | Budget validation failure |
| Missing PO | Unmapped purchase order |

These sample documents are intended for demonstration and testing.

## Repository Structure

```text
invoice-agent/
├── app.py
├── agent.py
├── agent_tools.py
├── approval_workflow.py
├── auth.py
├── checks.py
├── matcher.py
├── db.py
├── db_store.py
├── setup_agent_tables.py
├── schema.sql
├── schema_agent.sql
├── requirements.txt
├── .gitignore
├── demo_test_invoices/
├── data/
└── tests/
```

## Security and Financial Controls

- API keys and credentials must remain in local environment variables.
- Database operations use PostgreSQL.
- Approval stages enforce human oversight.
- Payment scheduling requires an approved request.
- Payment operations are role-restricted.
- Duplicate scheduling is guarded against.

## Project Objective

The objective is to demonstrate how AI can improve accounts payable workflows while retaining deterministic financial controls, human decision-making, and traceable processing.

**Built for JKLU AI Buildathon 2026 — PS-09.**