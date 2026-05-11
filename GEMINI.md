# FBIManager Project Context

## Project Overview
FBIManager (Facebook Interaction Manager) is a FastAPI-based application designed to manage and automate Facebook Page interactions. It supports multi-account management, provides real-time monitoring via Webhooks, automates data synchronization (posts, comments, private messages, and insights), and employs Large Language Models (LLMs) with customizable personas to generate intelligent automated replies.

### Core Technologies
- **Backend:** Python 3.12+, FastAPI, Uvicorn, HTTPX (for Graph API and LLM requests).
- **Database:** SQLite (local storage for accounts, posts, comments, private messages, insights, and configs).
- **Frontend:** Jinja2 templates, Vanilla CSS, and Vanilla JavaScript.
- **Environment Management:** [uv](https://github.com/astral-sh/uv) is used for dependency management and script execution.
- **AI Integration:** OpenAI-style Chat Completion APIs (e.g., GPT, Qwen, DeepSeek) with Jinja2-based prompt templates.
- **Facebook Integration:** Graph API v25.0, including Webhook support for real-time interactions and Messenger (Private Messages) management.

### Key Architecture Components
- `app/application.py`: App factory, lifecycle management, and security middleware (Auth, CSRF, CSP).
- `app/registry.py`: Global registry for service singletons and background task status tracking.
- `app/services/sync.py`: Handles batch synchronization of posts, comments, and multi-level insights. Uses background workers and the registry for progress tracking via SSE (`/api/sync/stream`).
- `app/services/chat_sync.py`: Manages synchronization of Facebook Page conversations and messages.
- `app/services/webhook.py`: Processes real-time Facebook events (comments, messages) and coordinates immediate AI responses.
- `app/services/facebook.py`: Low-level wrapper for Facebook Graph API v25.0. Implements a robust `edge_plan` fallback strategy (`published_posts` -> `posts` -> `feed`) and Messenger endpoints.
- `app/services/ai_reply.py`: Core logic for generating AI responses using template-based personas.
- `app/services/monitor.py`: Background task scheduler for periodic data refresh. Supports **Auto-monitor** scheduling for automated post discovery.
- `app/routes/webhook.py`: Entry point for Facebook Webhook verification and event handling.
- `app/routes/api.py`: Provides REST endpoints for account management, task control, auto-monitor configuration, and LLM connectivity testing.
- `app/routes/web.py`: Web UI routes, including the Content Center, Monitor Center, and the new **Chat Dashboard**.

### Performance Optimization
- **Background Workers:** Long-running synchronization tasks (posts, chats) are executed by background workers. Progress is tracked in `app/registry.py` to ensure the UI remains responsive and provides real-time feedback.
- **Lazy Loading:** The Content Center implements lazy loading for comments. Initial page load only fetches post metadata (default limit: 50 posts), and comments are fetched asynchronously via AJAX when a post is expanded.
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
- **CSP:** A strict Content Security Policy is enforced in `app/application.py`, carefully balanced to allow necessary inline scripts and styles used by the UI.

### Implementation Guidelines
- **Python Style:** Use Python 3.12 features (e.g., `dataclass(slots=True)`). Adhere to `ruff` for linting.
- **Task Registry:** Use `app.registry.update_task_status` for any long-running operation to provide UI visibility.
- **Persona Management:** AI behaviors are defined in `prompts/*.j2`. The system uses a registry and database (`model_configs.prompt_template`) to manage and switch personas dynamically via the API.
- **Multi-Account:** All services must handle multiple Facebook Page configurations dynamically using the `repositories.py` DAO layer.
- **Async First:** All network I/O and database operations must be asynchronous to ensure high responsiveness.

### Testing and Validation
- **Webhook Testing:** Verify Facebook Webhook integrations by ensuring the server's endpoint is reachable and correctly configured in the Facebook Developer Portal.
- **AI Verification:** Use the "Test Configuration" feature in the UI to verify LLM connectivity and prompt rendering.
- **Manual Verification:** After significant changes, manually trigger sync or monitor tasks in the UI to ensure behavioral correctness. Verify both Post Sync and Chat Sync progress in the respective dashboards.
