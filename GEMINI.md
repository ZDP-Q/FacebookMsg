# FBIManager Project Context

## Project Overview
FBIManager (Facebook Interaction Manager) is a FastAPI-based application designed to manage and automate Facebook Page interactions. It supports multi-account management, provides real-time monitoring via Webhooks, automates data synchronization (posts, comments, and insights), and employs Large Language Models (LLMs) with customizable personas to generate intelligent automated replies.

### Core Technologies
- **Backend:** Python 3.12+, FastAPI, Uvicorn, HTTPX (for Graph API and LLM requests).
- **Database:** SQLite (local storage for accounts, posts, comments, insights, and configs).
- **Frontend:** Jinja2 templates, Vanilla CSS, and Vanilla JavaScript.
- **Environment Management:** [uv](https://github.com/astral-sh/uv) is used for dependency management and script execution.
- **AI Integration:** OpenAI-style Chat Completion APIs (e.g., GPT, Qwen, DeepSeek) with Jinja2-based prompt templates.
- **Facebook Integration:** Graph API v25.0, including Webhook support for real-time interactions.

### Key Architecture Components
- `app/application.py`: App factory, lifecycle management, and security middleware (Auth, CSRF, CSP).
- `app/services/sync.py`: Handles batch synchronization of posts, comments, and multi-level insights. Includes a Server-Sent Events (SSE) endpoint (`/api/sync/stream`) for real-time progress feedback.
- `app/services/webhook.py`: Processes real-time Facebook events and coordinates immediate AI responses.
- `app/services/facebook.py`: Low-level wrapper for Facebook Graph API v25.0. Implements a robust `edge_plan` fallback strategy (`published_posts` -> `posts` -> `feed`) to handle varied account permissions.
- `app/services/ai_reply.py`: Core logic for generating AI responses using template-based personas.
- `app/services/monitor.py`: Background task scheduler for periodic data refresh.
- `app/routes/webhook.py`: Entry point for Facebook Webhook verification and event handling.
- `app/routes/api.py`: Provides REST endpoints for account management, prompt configuration, and LLM connectivity testing.
- `prompts/`: Directory containing Jinja2 templates for different AI "personas".
- `app/repositories.py`: Data Access Object (DAO) layer for SQLite, implementing UPSERT logic for bulk imports and IP-based login throttling.

## Building and Running

### Prerequisites
- Python 3.12 or higher.
- `uv` installed (`pip install uv`).

### Key Commands
- **Install Dependencies:**
  ```bash
  uv sync
  ```
- **Initialize/Reset Admin Password:**
  ```bash
  # REQUIRED: At least 16 characters. Set ADMIN_PASSWORD environment variable.
  export ADMIN_PASSWORD="your-strong-password-here"
  uv run python reset_pwd.py
  ```
- **Run the Application (Development):**
  ```bash
  uv run python main.py
  ```
- **Deployment (Docker):**
  ```bash
  # Using docker-compose
  bash scripts/deploy.sh
  ```

### Startup Script
- `scripts/start.sh`: Unified entry point for both Docker and host environments.

## Development Conventions

### Security Standards
- **Authentication:** Admin access protected by PBKDF2-SHA256 (390,000 iterations). Passwords MUST be at least 16 characters long. Login attempts are throttled by IP (`admin_login_attempts` table) and locked after multiple failures.
- **Session Management:** Explicit session lifecycle management (8 hours TTL) and CSRF protection (Origin/Referer validation for sensitive API calls).
- **Data Privacy:** Access tokens and API keys are stored in the local SQLite database, never hardcoded.

### Implementation Guidelines
- **Python Style:** Use Python 3.12 features (e.g., `dataclass(slots=True)`). Adhere to `ruff` for linting.
- **Persona Management:** AI behaviors are defined in `prompts/*.j2`. The system uses a registry and database (`model_configs.prompt_template`) to manage and switch personas dynamically via the API.
- **Multi-Account:** All services must handle multiple Facebook Page configurations dynamically using the `repositories.py` DAO layer (e.g., `bulk_import_accounts` with UPSERT).
- **Async First:** All network I/O and database operations must be asynchronous to ensure high responsiveness.

### Testing and Validation
- **Webhook Testing:** Verify Facebook Webhook integrations by ensuring the server's endpoint is reachable and correctly configured in the Facebook Developer Portal.
- **AI Verification:** Use the "Test Configuration" feature in the UI to verify LLM connectivity and prompt rendering.
- **Manual Verification:** After significant changes, manually trigger sync or monitor tasks in the UI to ensure behavioral correctness.
