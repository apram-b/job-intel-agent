"""Read-only AWS launch checks; never provisions resources or prints credentials."""

import argparse
import ipaddress
import json
import subprocess
import sys


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--owner-cidr", required=True)
    args = p.parse_args()
    address = ipaddress.ip_network(args.owner_cidr)
    if address.version != 4 or address.prefixlen != 32 or not address.network_address.is_global:
        raise SystemExit("Use your public IPv4 address with /32")

    def aws(*command):
        result = subprocess.run(
            ["aws", "--profile", args.profile, "--region", "ap-south-1", *command, "--output", "json"],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(
                "AWS check failed: "
                + " ".join(command[:2])
                + ". Verify this account and its permissions locally."
            )
        return json.loads(result.stdout)

    identity = aws("sts", "get-caller-identity")
    bundles = aws("lightsail", "get-bundles")["bundles"]
    selected = next((b for b in bundles if b["bundleId"] == "small_3_0" and b.get("isActive")), None)
    if not selected or selected["price"] > 12 or selected["ramSizeInGb"] < 2:
        raise SystemExit(
            "Expected <=US$12, 2 GB bundle is unavailable. Do not provision a substitute automatically."
        )
    blueprints = aws("lightsail", "get-blueprints")["blueprints"]
    if not any(b["blueprintId"] == "ubuntu_24_04" and b.get("isActive") for b in blueprints):
        raise SystemExit("Ubuntu 24.04 blueprint is unavailable; review the deployment configuration.")
    print(
        json.dumps(
            {
                "account": identity["Account"],
                "region": "ap-south-1",
                "bundle": selected["bundleId"],
                "monthly_compute_usd": selected["price"],
                "owner_ssh_cidr": str(address),
                "additional_checks_required": [
                    "Confirm this paid AWS account supports the CloudFront FREE flat-rate subscription.",
                    "Confirm current exact-model prices, owner-only SNS subscription, and total estimated charges <= US$20.",
                    "Do not publish until the seven-day pilot, 50 labels, backup restore and cold-visit checks pass.",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        sys.exit(str(exc))
