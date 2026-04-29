# FBIManager (Facebook 互动管理系统)

[English Version](./README.md)

一个基于 FastAPI 的 Facebook 互动管理系统，集成 AI 自动回复与多账号监控功能。

### 核心特性

- **安全性优先**：
  - **高级身份验证**：基于管理员账号的身份验证，使用 PBKDF2-SHA256 算法及 39 万次迭代。
  - **防暴力破解**：内置基于 IP 的登录锁定机制 (`admin_login_attempts`)，多次错误尝试后将自动锁定。
  - **安全会话**：采用 HTTP-only 和 SameSite 属性的安全 Cookie 会话管理。
  - **CSRF 防护**：对所有核心写入操作实施强制同源 (Origin/Referer) 校验，有效防御跨站请求伪造。
  - **安全响应头**：配置严格的 CSP、X-Frame-Options 等安全响应头。
- **智能监控与回复**：
  - **多 AI 角色支持**：支持通过 Jinja2 模板自定义 AI 人设。可在 UI 界面中动态切换活跃角色（设置存储于 `model_configs.prompt_template`）。
  - **Webhook 集成**：通过 Facebook Webhooks 实现实时互动处理，支持对新评论和消息的即时 AI 回复。
  - **实时数据同步**：深度适配 Facebook Graph API v25.0，采用 Server-Sent Events (SSE) 技术提供同步进度的实时反馈。支持多层级 Edge 回退策略（published_posts -> posts -> feed），确保数据同步的高可靠性。
  - **智能补发机制**：自动检测在 Facebook 网页端被手动删除的 AI 回复，并支持系统重新生成或补发。
- **管理能力**：
  - **多账号与页面管理**：利用具备 UPSERT 逻辑的 DAO 层高效管理多个 Facebook 页面和账号，支持配置的批量导入。
  - **数据库驱动配置**：所有设置（账号、模型、人设）均存储在本地 SQLite 数据库中，无需手动编辑文件即可实现动态更新。
  - **可视化面板**：提供直观的评论中心、帖子监控、同步状态展示以及 AI 角色选择。
  - **连通性测试**：内置 LLM API 连通性与模型设置的实时验证功能。

### 项目架构

- `app/routes/webhook.py`：Facebook 实时事件处理入口。
- `app/services/facebook.py`：高度封装的 Graph API v25.0 客户端。
- `app/services/ai_reply.py`：基于 Jinja2 模板的 AI 人设回复核心逻辑。
- `app/services/sync.py`：处理后台数据同步与流式更新。
- `prompts/`：基于 Jinja2 的 AI 人设模板目录。
- `data/facebookmsg.sqlite3`：存储所有持久化数据与系统配置的 SQLite 数据库。

### 快速启动

1. **安装依赖**：
   ```bash
   uv sync
   ```

2. **初始化管理员**：
   ```bash
   # 设置 ADMIN_PASSWORD 环境变量 (必须 16 位及以上)
   export ADMIN_PASSWORD="your-secure-password-here"
   uv run python reset_pwd.py
   ```
   *默认用户名为 `admin`。必须设置 16 位及以上的强密码。*

3. **运行应用**：
   ```bash
   uv run python main.py
   ```
   访问 `http://127.0.0.1:8000`。

### Webhook 配置

若要启用实时更新，请在 Facebook 开发者中心配置您的应用：
1. **回调 URL (Callback URL)**：`https://your-domain.com/webhook`
2. **验证令牌 (Verify Token)**：设置自定义令牌（需与 FBIManager 中的配置匹配）。
3. **订阅项**：订阅 `feed`（针对帖子/评论）和 `messages`（针对直接互动）。

### 配置说明

- **账号管理**：添加、编辑或批量导入多个 Facebook 页面配置。
- **模型与人设**：配置 LLM 服务商，并从 `prompts/` 目录中选择活跃的 AI 角色。
- **批量操作**：利用导入/导出功能进行配置迁移或备份。

### 注意事项

- **数据库备份**：生产环境下请定期备份 `data/facebookmsg.sqlite3` 数据库文件。
- **API 权限**：确保使用的 Page Access Token 拥有 `pages_manage_metadata`、`pages_read_engagement` 和 `pages_messaging` 等必要权限。
