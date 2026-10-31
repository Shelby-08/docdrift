# DocSentry

## Overview
DocSentry is a GitHub App backend designed to detect documentation drift in Pull Requests.
It receives webhooks, validates payloads, and prepares the context for analysis.

## Current Stage
**Stage 1: Backend Foundation**
- Webhook ingestion
- Signature verification
- Payload validation
- Logging

## Setup
1. Create a virtual environment: `python -m venv .venv`
2. Install dependencies: `pip install -e ".[dev]"`
3. Copy `.env.example` to `.env` and fill in the values.

## Environment Variables
- `GITHUB_APP_ID`: Your GitHub App ID.
- `GITHUB_PRIVATE_KEY`: Your RSA Private Key.
- `GITHUB_WEBHOOK_SECRET`: Secret for webhook verification.
- `PORT`: Port to run the server (default 3000).

## Running
Run the server:
```bash
python -m docsentry
```

## License
MIT, see [LICENSE](LICENSE).

