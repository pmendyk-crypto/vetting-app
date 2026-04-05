# Quick Start

## Start Locally

1. Create and activate a virtual environment if needed:
   `py -m venv .venv`
   `.venv\Scripts\Activate.ps1`
2. Install dependencies:
   `python -m pip install --upgrade pip`
   `pip install -r requirements.txt`
3. Create the local env file once:
   `Copy-Item .env.local.example .env.local`
4. Start the app:
   `.\scripts\run-local.ps1 -Reload`

Local URL:

- `http://127.0.0.1:8000`

## What To Expect

- public landing page at `/`
- sign-in at `/login`
- MFA verification at `/login/mfa` for enrolled users
- account management and MFA setup at `/account`
- owner dashboard at `/owner` for superusers
- admin dashboard at `/admin`
- practitioner dashboard at `/radiologist`

## Optional Isolated Test Environment

1. Bootstrap:
   `.\scripts\setup-test-env.ps1`
2. Run:
   `.\scripts\run-test-local.ps1`

Test URL:

- `http://127.0.0.1:8001`

## Current Notes

- the live management path is `/owner*`, not the older `/mt/*` route set
- `develop` is the staging branch and `main` is the production branch
- password reset and MFA flows are part of the normal app path and should be included in smoke testing after local startup
