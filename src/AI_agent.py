from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

from project_paths import CONFIG_DIR


def load_llm_config() -> dict[str, Any]:
    agent = os.getenv("LITERATURE_AGENT", "deepseek").strip().lower()
    explicit_path = os.getenv("LITERATURE_AGENT_CONFIG", "").strip()
    config_path = Path(explicit_path) if explicit_path else default_config_path(agent)
    config = default_agent_config(agent)

    if config_path.exists():
        try:
            file_config = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(file_config, dict):
                config.update(file_config)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"AI agent 配置文件不是合法 JSON：{config_path}，{exc}") from exc

    apply_environment_overrides(config)
    placeholder_keys = {
        "",
        "填入你的 DeepSeek API Key",
        "sk-your-deepseek-api-key",
        "sk-your-openai-api-key",
        "sk-ant-your-claude-api-key",
    }
    if str(config.get("api_key", "")).strip() in placeholder_keys:
        config["api_key"] = ""
    return config


def default_config_path(agent: str) -> Path:
    mapping = {
        "deepseek": CONFIG_DIR / "deepseek_v4pro.json",
        "chatgpt": CONFIG_DIR / "chatgpt.json",
        "openai": CONFIG_DIR / "chatgpt.json",
        "claude": CONFIG_DIR / "claude.json",
        "anthropic": CONFIG_DIR / "claude.json",
    }
    return mapping.get(agent, CONFIG_DIR / f"{agent}.json")


def default_agent_config(agent: str) -> dict[str, Any]:
    if agent in {"chatgpt", "openai"}:
        return {
            "provider": "openai",
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "endpoint": "responses",
            "temperature": 0.2,
            "max_tokens": 2200,
            "timeout_seconds": 180,
            "sleep_seconds": 0.2,
        }
    if agent in {"claude", "anthropic"}:
        return {
            "provider": "anthropic",
            "api_key": "",
            "base_url": "https://api.anthropic.com",
            "model": "claude-3-5-sonnet-latest",
            "endpoint": "anthropic_messages",
            "temperature": 0.2,
            "max_tokens": 2200,
            "timeout_seconds": 180,
            "sleep_seconds": 0.2,
            "anthropic_version": "2023-06-01",
        }
    return {
        "provider": "deepseek",
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-pro",
        "endpoint": "chat_completions",
        "temperature": 0.2,
        "max_tokens": 2200,
        "timeout_seconds": 180,
        "sleep_seconds": 0.2,
        "json_mode": True,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }


def apply_environment_overrides(config: dict[str, Any]) -> None:
    env_api_key = (
        os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("CLAUDE_API_KEY")
        or os.getenv("LITERATURE_API_KEY")
    )
    if env_api_key:
        config["api_key"] = env_api_key
    for env_name, key in (
        ("LITERATURE_BASE_URL", "base_url"),
        ("LITERATURE_MODEL", "model"),
        ("DEEPSEEK_BASE_URL", "base_url"),
        ("DEEPSEEK_MODEL", "model"),
        ("OPENAI_BASE_URL", "base_url"),
        ("OPENAI_MODEL", "model"),
        ("ANTHROPIC_MODEL", "model"),
    ):
        value = os.getenv(env_name)
        if value:
            config[key] = value


def post_llm_json(endpoint: str, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    provider = str(config.get("provider", "")).lower()
    if provider in {"anthropic", "claude"}:
        headers = {
            "x-api-key": str(config["api_key"]),
            "anthropic-version": str(config.get("anthropic_version", "2023-06-01")),
            "Content-Type": "application/json",
        }
    else:
        headers = {
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        }

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=int(config.get("timeout_seconds", 180)),
            )
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
            return response.json()
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2 * attempt)
    raise RuntimeError(str(last_error))


def extract_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    texts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                texts.append(text)
    if texts:
        return "\n".join(texts)
    raise RuntimeError("无法从 API 响应中提取文本")


def extract_json_object(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    raise RuntimeError("模型响应中没有找到 JSON 对象")
