from __future__ import annotations

from typing import Any

import httpx
from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from app.config import AppConfig, PROJECT_ROOT

_PROMPT_DIR = PROJECT_ROOT / "prompts"
_DEFAULT_TEMPLATE = (
    "主页名称: {{ page_name or '未提供' }}\n"
    "帖子内容: {{ post_message or '未提供' }}\n"
    "评论用户: {{ author_name or '匿名用户' }}\n"
    "评论内容: {{ comment_message or '（空）' }}\n"
    "{% if parent_comment_message %}被回复的原评论: {{ parent_comment_message }}\n{% endif %}"
    "你的人设如下：\n"
    "- 35 岁男性，白手起家的投资人，曾创立并出售科技公司，已实现财务自由。\n"
    "- 气质自信、沉稳、有掌控力；生活重心是投资、旅行、健身与高质量生活。\n"
    "- 爱好包括健身训练、探索旅行、户外活动、偶尔下厨、发掘美食餐厅。\n"
    "- 给人感觉冷静、可靠、有吸引力，能让人安心。\n\n"
    "性格与互动风格：\n"
    "- 成熟、稳定、略带主导感；自信但不张扬。\n"
    "- 保护欲、观察力强，偶尔带一点俏皮和轻微调侃。\n"
    "- 关心对方时温暖但不黏人，不刻意讨好。\n"
    "- 说话像真实男性，不要像 AI 助手，不要说教。\n\n"
    "表达要求：\n"
    "- 回复自然、口语化、直接，避免生硬或官腔。\n"
    "- 大多数回复控制在 1-3 句，简洁但有温度。\n"
    "- 不要输出解释、分析、步骤、标题，不要加引号，不要前缀。\n"
    "- 可以轻微调情和玩笑，但保持分寸、自然推进，不要突兀。\n\n"
    "语言适配规则（必须遵守）：\n"
    "- 回复语言必须与“评论内容”的主要语言保持一致。\n"
    "- 如果“评论内容”很短或语言不明确，则参考“被回复的原评论”的主要语言。\n"
    "- 如果仍无法判断，则默认使用简体中文。\n"
    "- 不要额外说明你在切换语言，直接用对应语言回复。\n\n"
    "任务：\n"
    "请直接输出一条适合发在 Facebook 评论区的回复。"
)


def _build_user_prompt(
    *,
    page_name: str,
    post_message: str,
    comment_message: str,
    author_name: str,
    parent_comment_message: str = "",
    template_name: str = "reply_prompt.j2",
) -> str:
    try:
        env = Environment(
            loader=FileSystemLoader(str(_PROMPT_DIR)),
            autoescape=False,
            keep_trailing_newline=True,
        )
        template = env.get_template(template_name)
    except (TemplateNotFound, OSError):
        from jinja2 import Template
        template = Template(_DEFAULT_TEMPLATE)

    return template.render(
        page_name=page_name,
        post_message=post_message,
        comment_message=comment_message,
        author_name=author_name,
        parent_comment_message=parent_comment_message,
    ).strip()


class AIReplyService:
    def __init__(self, config: AppConfig):
        self.config = config

    def _chat_completions_url(self) -> str:
        base_url = self.config.ai_api_base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def _looks_like_unsupported_param(self, detail: str) -> bool:
        text = (detail or "").lower()
        markers = [
            "unknown parameter",
            "unknown field",
            "unsupported",
            "unexpected field",
            "extra inputs",
            "not permitted",
            "unrecognized",
            "invalid parameter",
        ]
        return any(m in text for m in markers)

    async def generate_reply(
        self,
        *,
        page_name: str,
        post_message: str,
        comment_message: str,
        comment_author: str,
        parent_comment_message: str = "",
        template_name: str = "reply_prompt.j2",
    ) -> str:
        if not self.config.ai_enabled:
            raise RuntimeError("AI 配置不完整，请先在 config.json 中填写 AI_API_BASE_URL、AI_API_KEY 和 AI_MODEL")

        user_content = _build_user_prompt(
            page_name=page_name,
            post_message=post_message,
            comment_message=comment_message,
            author_name=comment_author,
            parent_comment_message=parent_comment_message,
            template_name=template_name,
        )

        payload_base: dict[str, Any] = {
            "model": self.config.ai_model,
            "temperature": 0.4,
            "max_tokens": 180,
            "stream": False,
            "messages": [
                {"role": "user", "content": user_content},
            ],
        }

        # Prefer non-thinking mode for faster comment replies.
        payload_fast = {
            **payload_base,
            "enable_thinking": False,
            "reasoning": {"effort": "none"},
        }

        headers = {
            "Authorization": f"Bearer {self.config.ai_api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=35.0) as client:
            response = await client.post(self._chat_completions_url(), headers=headers, json=payload_fast)

            if response.status_code >= 400:
                detail = response.text
                try:
                    detail = response.json().get("error", {}).get("message", detail)
                except ValueError:
                    pass

                # Some OpenAI-compatible providers reject custom reasoning fields.
                if self._looks_like_unsupported_param(detail):
                    response = await client.post(self._chat_completions_url(), headers=headers, json=payload_base)

        if response.status_code >= 400:
            detail = response.text
            try:
                detail = response.json().get("error", {}).get("message", detail)
            except ValueError:
                pass
            raise RuntimeError(detail)

        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("AI 接口未返回可用内容")

        content = choices[0].get("message", {}).get("content", "").strip()
        if not content:
            raise RuntimeError("AI 接口返回了空内容")
        return content

    async def test_connection(self) -> str:
        """Tests the connection to the LLM with a simple prompt."""
        if not self.config.ai_api_base_url or not self.config.ai_api_key or not self.config.ai_model:
            raise RuntimeError("请先填写 AI_API_BASE_URL、AI_API_KEY 和 AI_MODEL")

        payload = {
            "model": self.config.ai_model,
            "messages": [
                {"role": "user", "content": "hi"},
            ],
            "max_tokens": 5,
        }

        headers = {
            "Authorization": f"Bearer {self.config.ai_api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(self._chat_completions_url(), headers=headers, json=payload)
                if response.status_code >= 400:
                    detail = response.text
                    try:
                        detail = response.json().get("error", {}).get("message", detail)
                    except ValueError:
                        pass
                    raise RuntimeError(f"连接失败 ({response.status_code}): {detail}")

                return "连接成功！AI 已响应。"
            except httpx.RequestError as exc:
                raise RuntimeError(f"网络请求失败: {exc}") from exc
