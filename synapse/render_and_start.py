#!/usr/bin/env python3

import os
from pathlib import Path


TEMPLATE_PATH = Path("/data/homeserver.template.yaml")
OUTPUT_PATH = Path("/data/homeserver.rendered.yaml")
REQUIRED_VARS = [
    "DOMAIN",
    "MATRIX_SUBDOMAIN",
    "LIVEKIT_SUBDOMAIN",
    "POSTGRES_PASSWORD",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "SYNAPSE_REPORT_STATS",
    "MACAROON_SECRET_KEY",
    "REGISTRATION_SHARED_SECRET",
    "FORM_SECRET",
]


def render_config() -> None:
    missing = [name for name in REQUIRED_VARS if not os.environ.get(name)]
    if missing:
        raise SystemExit(
            "Missing required environment variables for Synapse config: "
            + ", ".join(missing)
        )

    content = TEMPLATE_PATH.read_text()
    for name in REQUIRED_VARS:
        content = content.replace("${" + name + "}", os.environ[name])
    OUTPUT_PATH.write_text(content)


def main() -> None:
    render_config()
    os.execv("/start.py", ["/start.py"])


if __name__ == "__main__":
    main()
