# FBIManager (Facebook Interaction Manager)

[中文版本 (Chinese Version)](./README.zh-CN.md)

A FastAPI-based Facebook interaction management system integrated with AI automated replies and multi-account monitoring.

### Core Features

- **Security First**:
  - Administrator-based authentication using PBKDF2-SHA256 with 390,000 iterations.
  - Built-in IP-based login locking to prevent brute-force attacks (locks after multiple failed attempts).
  - Secure session management with HTTP-only and SameSite cookies.
  - CSRF protection for core write operations via mandatory origin/referer checks.
  - Strict security response headers (CSP, X-Frame-Options, etc.).
- **Intelligent Monitoring & Reply**:
  - **Multiple AI Personas**: Support for customizable personas via Jinja2 templates (e.g., "Elio" for charismatic investment advice, "ElyaVena" for specialized interactions). Switch personas dynamically via the UI.
  - **Webhook Integration**: Real-time interaction processing via Facebook Webhooks, enabling immediate AI responses to new comments and messages.
  - **Enhanced Synchronization**: Deeply adapted to Facebook Graph API v25.0, supporting a multi-level edge fallback strategy (`published_posts` -> `posts` -> `feed`) for high reliability.
  - **Smart Re-generation**: Detects if an AI reply was manually deleted on the Facebook web interface and allows the system to re-generate or re-send the reply.
- **Management Capabilities**:
  - **Multi-Account & Page Management**: Efficiently manage multiple Facebook Pages and accounts. Supports bulk import/export of account configurations.
  - **Database-Driven Configuration**: All settings (accounts, models, personas) are stored in a local SQLite database, allowing for persistent and dynamic updates without manual file edits.
  - **Visual Dashboard**: Comprehensive views for comment management, post monitoring, synchronization status, and persona selection.
  - **Connectivity Test**: Built-in validation for LLM API connectivity and model settings.

### Project Architecture

- `app/routes/webhook.py`: Entry point for real-time Facebook event handling.
- `app/services/facebook.py`: Encapsulated Graph API v25.0 client.
- `app/services/ai_reply.py`: Core logic for persona-based AI responses using Jinja2 templates.
- `app/services/sync.py`: Handles background data synchronization and streaming updates.
- `prompts/`: Directory for Jinja2-based AI persona templates.
- `data/facebookmsg.sqlite3`: SQLite database for all persistent data and configurations.

### Quick Start

1. **Install Dependencies**:
   ```bash
   uv sync
   ```

2. **Initialize Administrator**:
   ```bash
   uv run python reset_pwd.py
   ```
   *The default username is `admin`. A strong password (at least 16 characters) is required.*

3. **Run the Application**:
   ```bash
   uv run python main.py
   ```
   Access `http://127.0.0.1:8000`.

### Webhook Configuration

To enable real-time updates, configure your Facebook App:
1. **Callback URL**: `https://your-domain.com/webhook`
2. **Verify Token**: Set a custom token in your app settings (matching the one in FBIManager).
3. **Subscriptions**: Subscribe to `feed` (for posts/comments) and `messages` (for direct interactions).

### Configuration Guide

- **Account Management**: Add, edit, or import multiple Facebook Page configurations.
- **Model & Persona**: Configure LLM providers and select active personas from the `prompts/` directory.
- **Bulk Actions**: Use the import/export features to migrate or backup configurations.

### Important Notes

- **Database Backup**: Regularly back up `data/facebookmsg.sqlite3` in production environments.
- **API Permissions**: Ensure your Page Access Token has the necessary permissions, such as `pages_manage_metadata`, `pages_read_engagement`, and `pages_messaging`.
