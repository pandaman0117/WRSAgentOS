"""Command-line entry; Python examples call serve_node() directly."""

import argparse
import asyncio

from wrs_agent.nodes.serve import serve_node
from wrs_agent.processes import LocalStack


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=["wrs", "agent", "tts", "voice", "launch"])
    parser.add_argument("--endpoint", default="tcp/127.0.0.1:7447")
    parser.add_argument("--site", default="local")
    parser.add_argument("--env-id", default="arm01")
    parser.add_argument("--journal")
    parser.add_argument("--node-id")
    parser.add_argument("--bindings")
    parser.add_argument("--model-provider", choices=["mock", "glm"], default="mock")
    parser.add_argument("--live-model", action="store_true")
    parser.add_argument("--backend", choices=["mock", "wrs_virtual"], default="mock")
    parser.add_argument("--duration", type=float, default=0.4)
    parser.add_argument(
        "--deferred-planner",
        action="store_true",
        help="offline test fixture; no GLM request is sent",
    )
    parser.add_argument(
        "--fault",
        choices=[
            "grasp",
            "grasp_once",
            "localization",
            "localization_once",
            "unknown",
            "inconclusive",
            "stop_unknown",
        ],
    )
    args = parser.parse_args()
    if args.model_provider == "glm" and (not args.live_model or args.deferred_planner):
        parser.error("GLM requires --live-model and cannot use --deferred-planner")
    if args.duration <= 0 or args.duration > 30:
        parser.error("duration must be in (0, 30]")
    if args.role == "launch":
        async with LocalStack(
            duration=args.duration,
            port=7447,
            site=args.site,
            env_id=args.env_id,
            backend=args.backend,
            model_provider=args.model_provider,
            live_model=args.live_model,
            bindings=args.bindings,
        ) as stack:
            print(
                f"ready {args.backend} stack: {stack.endpoint} {stack.env_id}; Ctrl+C to stop",
                flush=True,
            )
            await asyncio.Event().wait()
    else:
        await serve_node(**vars(args))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
