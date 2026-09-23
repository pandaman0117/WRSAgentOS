"""Check model endpoint reachability without a key, model request or robot process."""

import argparse
import asyncio
import os

import httpx
from pydantic import ValidationError

from wrs_agent.errors import error_info
from wrs_agent.planner.providers.llm import LLMConfig, http_transport, transport_error_code


async def check(config):
    # No Authorization header, prompts or API keys are read or sent.
    try:
        async with httpx.AsyncClient(
            transport=http_transport(config), timeout=8, follow_redirects=False
        ) as client:
            response = await client.get(config.base_url + "/")
        print(f"HTTP 已连通：状态码 {response.status_code}（未验证 API Key 或模型权限）。")
        return 0
    except httpx.TimeoutException:
        error = error_info("llm_timeout")
    except httpx.HTTPError as exc:
        error = error_info(transport_error_code(exc))
    print(f"连接失败（{error.code}）：{error.message}")
    return 1


def config_error(code):
    error = error_info(code)
    print(f"配置错误（{error.code}）：{error.message}")
    return 1


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    # Validate the endpoint and proxy rules the client uses; no model selection is needed.
    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    if not base_url:
        return config_error("llm_base_url_missing")
    try:
        config = LLMConfig(
            model="connection-check",
            base_url=base_url,
            proxy=os.environ.get("LLM_PROXY", "").strip() or None,
        )
    except ValidationError as exc:
        return config_error(f"llm_{exc.errors(include_input=False)[0]['loc'][0]}_invalid")
    route = "经 LLM_PROXY 代理" if config.proxy else "直连（不读取系统或环境代理设置）"
    print(f"端点：{config.base_url}；网络模式：{route}")
    return asyncio.run(check(config))


if __name__ == "__main__":
    raise SystemExit(main())
