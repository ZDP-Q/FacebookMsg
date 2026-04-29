# FBIManager (Facebook Interaction Manager)

[中文版本 (Chinese Version)](./README.zh-CN.md)

A FastAPI-based Facebook interaction management system integrated with AI automated replies and multi-account monitoring.

### Core Features

- **Security First**:
  - **Administrator Authentication**: Uses PBKDF2-SHA256 with 390,000 iterations for secure password hashing.
  - **Anti-Brute Force**: Built-in IP-based login throttling and locking (`admin_login_attempts`) after multiple failed attempts.
  - **Secure Session Management**: HTTP-only and SameSite cookies with an 8-hour session TTL.
  - **CSRF Protection**: Mandatory Origin/Referer verification for sensitive API write operations.
  - **Security Headers**: Strict security response headers including CSP and X-Frame-Options.
- **Intelligent Monitoring & Reply**:
  - **Multiple AI Personas**: Support for customizable personas via Jinja2 templates. Switch personas dynamically via the UI (stored in `model_configs.prompt_template`).
  - **Webhook Integration**: Real-time interaction processing via Facebook Webhooks, enabling immediate AI responses to new comments and messages.
  - **Real-time Synchronization**: Deeply adapted to Facebook Graph API v25.0, using Server-Sent Events (SSE) to provide live feedback during synchronization. Supports a multi-level edge fallback strategy (`published_posts` -> `posts` -> `feed`) for high reliability.
  - **Smart Re-generation**: Detects if an AI reply was manually deleted on the Facebook web interface and allows the system to re-generate or re-send the reply.
- **Management Capabilities**:
  - **Multi-Account & Page Management**: Efficiently manage multiple Facebook Pages and accounts using a DAO layer with UPSERT logic for bulk imports.
  - **Database-Driven Configuration**: All settings (accounts, models, personas) are stored in a local SQLite database, allowing for persistent and dynamic updates.
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
   # Ensure uv is installed
   uv sync
   ```

2. **Initialize/Reset Administrator**:
   ```bash
   # Set the ADMIN_PASSWORD environment variable (MUST be at least 16 characters)
   export ADMIN_PASSWORD="your-secure-password-here"
   uv run python reset_pwd.py
   ```

3. **Run the Application**:
   ```bash
   uv run python main.py
   ```
   Access `http://127.0.0.1:38000`.
### Webhook Configuration

To enable real-time updates, configure your Facebook App:
1. **Callback URL**: `https://your-domain.com/webhook`
2. **Verify Token**: Set a custom token in your app settings (matching the one in FBIManager).
3. **Subscriptions**: Subscribe to `feed` (for posts/comments) and `messages` (for direct interactions).

### Important Notes

- **Database Backup**: Regularly back up `data/facebookmsg.sqlite3` in production.
- **API Permissions**: Ensure your Page Access Token has the necessary permissions, such as `pages_manage_metadata`, `pages_read_engagement`, and `pages_messaging`.
