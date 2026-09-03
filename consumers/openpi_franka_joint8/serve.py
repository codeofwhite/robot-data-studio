from __future__ import annotations

import argparse
import logging
from pathlib import Path


def build_policy(args):
    from openpi.policies import policy_config

    from consumers.openpi_franka_joint8.config import make_train_config

    config = make_train_config(
        dataset_root=args.dataset_root,
        training_root=args.training_root,
        base_checkpoint=args.base_checkpoint,
        experiment_name=args.experiment_name,
        num_train_steps=1,
    )
    policy = policy_config.create_trained_policy(
        config,
        args.checkpoint,
        default_prompt=args.default_prompt,
        sample_kwargs={"num_steps": args.inference_steps},
    )
    policy.metadata.update(
        {
            "policy_config": config.name,
            "checkpoint": str(args.checkpoint),
            "action_contract": "joint7_absolute_plus_gripper_closed_fraction",
            "action_horizon": int(config.model.action_horizon),
        }
    )
    return policy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the Studio Franka joint8 OpenPI policy")
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--base-checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--experiment-name", default="seed0_sanity")
    parser.add_argument("--default-prompt")
    parser.add_argument("--inference-steps", type=int, default=2)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    for name in ("dataset_root", "training_root", "base_checkpoint", "checkpoint"):
        setattr(args, name, getattr(args, name).expanduser().resolve())
    if args.inference_steps < 1:
        parser.error("--inference-steps must be positive")
    return args


def main() -> None:
    from openpi.serving.websocket_policy_server import WebsocketPolicyServer

    args = parse_args()
    policy = build_policy(args)
    logging.info(
        "Serving %s on ws://%s:%d with checkpoint %s",
        policy.metadata.get("policy_config"),
        args.host,
        args.port,
        args.checkpoint,
    )
    WebsocketPolicyServer(
        policy=policy,
        host=args.host,
        port=args.port,
        metadata=policy.metadata,
    ).serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, force=True)
    main()
