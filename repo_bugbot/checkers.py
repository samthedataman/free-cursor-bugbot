"""User-selected model providers. All requests carry text and return text."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

# (display name, default model, API base, credential environment variable)
PROVIDERS = {
    "codex": ("Codex CLI", "", "", ""),
    "claude": ("Claude Code CLI", "sonnet", "", ""),
    "ollama": ("Ollama", "qwen3:8b", "http://127.0.0.1:11434", ""),
    "openai": (
        "OpenAI / compatible",
        "gpt-4.1",
        "https://api.openai.com/v1",
        "OPENAI_API_KEY",
    ),
    "anthropic": (
        "Anthropic API",
        "claude-sonnet-4-6",
        "https://api.anthropic.com/v1",
        "ANTHROPIC_API_KEY",
    ),
    "gemini": (
        "Google Gemini",
        "gemini-2.5-flash",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
    ),
    "openrouter": (
        "OpenRouter",
        "",
        "https://openrouter.ai/api/v1",
        "OPENROUTER_API_KEY",
    ),
    "lmstudio": ("LM Studio", "", "http://127.0.0.1:1234/v1", ""),
}
FOCUSES = [
    "Correctness and regressions",
    "Security and data integrity",
    "Tests and edge cases",
]
TIMEOUT = 180
MAX_CHECKERS = 12
FINDING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["findings"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["severity", "file", "line", "title", "detail"],
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low"],
                    },
                    "file": {"type": "string"},
                    "line": {"type": "integer", "minimum": 1},
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                },
            },
        }
    },
}


def defaults(provider: str, index: int = 0) -> dict:
    label, model, endpoint, key = PROVIDERS[provider]
    return {
        "name": label,
        "provider": provider,
        "model": model,
        "endpoint": endpoint,
        "keyEnv": key,
        "focus": FOCUSES[index % len(FOCUSES)],
    }


def initial_config() -> dict:
    return {
        "checkers": [
            defaults(p, i) for i, p in enumerate(("codex", "claude", "ollama"))
        ]
    }


def validate_config(config: dict) -> list[dict]:
    rows = config.get("checkers") if isinstance(config, dict) else None
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_CHECKERS:
        raise ValueError(f"Choose between 1 and {MAX_CHECKERS} checkers.")
    result = []
    names = set()
    for i, row in enumerate(rows):
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("provider"), str)
            or row["provider"] not in PROVIDERS
        ):
            raise ValueError(f"Checker {i + 1} has an unknown provider.")
        checker = defaults(row["provider"], i)
        for key in checker:
            value = row.get(key, checker[key])
            if not isinstance(value, str) or len(value) > 1000 or "\x00" in value:
                raise ValueError(f"Invalid {key} for checker {i + 1}.")
            checker[key] = value.strip()
        if not checker["name"] or checker["name"].casefold() in names:
            raise ValueError("Give every checker a unique name.")
        names.add(checker["name"].casefold())
        if checker["provider"] not in ("codex", "claude"):
            if not checker["model"]:
                raise ValueError(f"Enter a model for {checker['name']}.")
            url = urlsplit(checker["endpoint"])
            local = url.scheme == "http" and url.hostname in (
                "localhost",
                "127.0.0.1",
                "::1",
            )
            if (
                not url.hostname
                or (url.scheme != "https" and not local)
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError(
                    "Use an HTTPS API base or a local HTTP endpoint, without credentials or query parameters."
                )
            if checker["keyEnv"] and not re.fullmatch(
                r"[a-zA-Z_][a-zA-Z_0-9]*", checker["keyEnv"]
            ):
                raise ValueError("Enter an environment variable name for the API key.")
        result.append(checker)
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def api_response(checker: dict, prompt: str) -> str:
    provider = checker["provider"]
    model = checker["model"]
    messages = [{"role": "user", "content": prompt}]
    key_name = checker["keyEnv"]
    key = os.getenv(key_name, "") if key_name else ""
    if key_name and not key:
        raise ValueError(
            f"Set {key_name} in the environment that launches Repo Bugbot."
        )
    headers = {"Content-Type": "application/json"}
    payload = {"model": model, "messages": messages}
    if provider == "anthropic":
        suffix = "/messages"
        headers.update({"anthropic-version": "2023-06-01", "x-api-key": key})
        payload["max_tokens"] = 4096
    else:
        suffix = "/chat/completions"
        if key:
            headers["Authorization"] = "Bearer " + key
        if provider == "ollama":
            suffix = "/api/chat"
            payload.update(stream=False, format=FINDING_SCHEMA)
    request = urllib.request.Request(
        checker["endpoint"].rstrip("/") + suffix,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(
            request, timeout=TIMEOUT
        ) as response:
            raw = response.read(2_000_001)
    except urllib.error.HTTPError as exc:
        raise ValueError(
            f"{PROVIDERS[provider][0]} returned HTTP {exc.code}. Check the model, endpoint and credentials."
        ) from None
    except (OSError, urllib.error.URLError):
        raise ValueError(
            f"Could not reach {PROVIDERS[provider][0]} at the configured endpoint."
        ) from None
    if len(raw) > 2_000_000:
        raise ValueError("The model response exceeded 2 MB.")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise TypeError("Invalid API response.")
    if (
        data.get("stop_reason") in ("max_tokens", "refusal")
        or data.get("done_reason") == "length"
    ):
        raise ValueError(
            "The provider ended its response before completing the review."
        )
    if provider == "ollama":
        return data["message"]["content"]
    if provider == "anthropic":
        return "".join(
            item.get("text", "")
            for item in data["content"]
            if isinstance(item, dict) and item.get("type") == "text"
        )
    choice = data["choices"][0]
    if not isinstance(choice, dict):
        raise TypeError("Invalid chat completion response.")
    if choice.get("finish_reason") in ("length", "content_filter"):
        raise ValueError(
            "The provider ended its response before completing the review."
        )
    return choice["message"]["content"]


def cli_response(checker: dict, prompt: str) -> str:
    # Never run agents in the repository being inspected. The immutable diff is supplied on stdin.
    with tempfile.TemporaryDirectory(prefix="bugbot-checker-") as folder:
        model = ["--model", checker["model"]] if checker["model"] else []
        output = Path(folder) / "answer.json"
        if checker["provider"] == "codex":
            schema = Path(folder) / "findings.schema.json"
            schema.write_text(json.dumps(FINDING_SCHEMA), encoding="utf-8")
            command = [
                "codex",
                "exec",
                "--skip-git-repo-check",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--ignore-user-config",
                "--disable",
                "shell_tool",
                "--disable",
                "unified_exec",
                "--disable",
                "apps",
                "--disable",
                "plugins",
                "-c",
                'web_search="disabled"',
                "--output-schema",
                str(schema),
                "--output-last-message",
                str(output),
                *model,
                "-",
            ]
        else:
            command = [
                "claude",
                "-p",
                "--tools",
                "",
                "--strict-mcp-config",
                "--mcp-config",
                '{"mcpServers":{}}',
                "--setting-sources",
                "",
                "--no-session-persistence",
                "--output-format",
                "text",
                *model,
            ]
        override = os.getenv("REPO_BUGBOT_" + checker["provider"].upper() + "_BIN")
        if override:
            command[0] = override
        try:
            result = subprocess.run(
                command,
                cwd=folder,
                input=prompt,
                text=True,
                check=False,
                capture_output=True,
                timeout=TIMEOUT,
            )
        except FileNotFoundError:
            raise ValueError(
                f"Install {command[0]} and make it available on PATH."
            ) from None
        except subprocess.TimeoutExpired:
            raise ValueError(
                f"{command[0]} timed out after {TIMEOUT} seconds."
            ) from None
        if result.returncode:
            raise ValueError(
                f"{command[0]} exited with code {result.returncode}. Check its login, version and selected model."
            )
        return (
            output.read_text(encoding="utf-8")
            if checker["provider"] == "codex"
            else result.stdout
        )


def ask(checker: dict, prompt: str) -> str:
    if checker["provider"] in ("codex", "claude"):
        return cli_response(checker, prompt)
    return api_response(checker, prompt)
