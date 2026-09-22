"""Check GLM network reachability without a key, model request or robot process."""

import argparse
import asyncio
import os

import httpx

from wrs_agent.errors import error_info
from wrs_agent.planner.providers.glm import CODING_BASE_URL, GLMConfig, transport_error_code


async def check(base_url):
    # No Authorization header, prompts or API keys are read or sent.
    try:
        async with httpx.AsyncClient(
            trust_env=False, timeout=8, follow_redirects=False
        ) as client:
            response = await client.get(base_url + "/")
        print(f"HTTP 已连通：状态码 {response.status_code}（未验证 API Key 或模型权限）。")
        return 0
    except httpx.TimeoutException:
        error = error_info("glm_timeout")
    except httpx.HTTPError as exc:
        error = error_info(transport_error_code(exc))
    print(f"连接失败（{error.code}）：{error.message}")
    return 1


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    # Validate the same endpoint allowlist; diagnosis does not need a model selection.
    config = GLMConfig(
        model="connection-check",
        base_url=os.environ.get("GLM_BASE_URL", CODING_BASE_URL).rstrip("/"),
    )
    print("网络模式：直连（不读取系统或环境代理设置）")
    return asyncio.run(check(config.base_url))


if __name__ == "__main__":
    raise SystemExit(main())
