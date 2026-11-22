"""Seed the 20-document / 50-question eval set through the public API.

Creates (or reuses) a knowledge base, uploads every document from
`eval/dataset.json`, waits for ingestion, then imports the question set as an
evaluation dataset. Credentials come from environment variables and are never
printed.

Usage:
    export AI_POWER_BASE_URL=http://192.168.29.100:8080/api
    export AI_POWER_EMAIL=demo@example.com
    export AI_POWER_PASSWORD='...'
    python scripts/seed_eval_platform.py --kb-name "检索评测集"
"""

import argparse
import json
import os
import time
from pathlib import Path

import httpx


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value == "":
        raise SystemExit(f"{name} is required")
    return value


def _wait_ready(client: httpx.Client, headers: dict[str, str], document_id: str) -> str:
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        response = client.get(f"/documents/{document_id}", headers=headers)
        response.raise_for_status()
        status = response.json()["status"]
        if status in {"ready", "failed"}:
            return status
        time.sleep(2)
    return "timeout"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AI_POWER_BASE_URL", "http://192.168.29.100:8080/api"),
    )
    parser.add_argument("--dataset", default="eval/dataset.json")
    parser.add_argument("--kb-name", default="检索评测集")
    parser.add_argument("--dataset-name", default="中文检索评测集 50 题")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    email = _require("AI_POWER_EMAIL")
    password = _require("AI_POWER_PASSWORD")
    bundle = json.loads(Path(args.dataset).read_text(encoding="utf-8"))

    with httpx.Client(base_url=base_url, timeout=120) as client:
        login = client.post("/auth/login", json={"email": email, "password": password})
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        kbs = client.get("/knowledge-bases", headers=headers)
        kbs.raise_for_status()
        kb = next((item for item in kbs.json() if item["name"] == args.kb_name), None)
        if kb is None:
            created = client.post("/knowledge-bases", json={"name": args.kb_name}, headers=headers)
            created.raise_for_status()
            kb = created.json()

        for document in bundle["documents"]:
            upload = client.post(
                f"/knowledge-bases/{kb['id']}/documents",
                files={
                    "file": (
                        document["filename"],
                        document["text"].encode("utf-8"),
                        "text/markdown",
                    )
                },
                headers=headers,
            )
            upload.raise_for_status()
            status = _wait_ready(client, headers, upload.json()["id"])
            if status != "ready":
                raise SystemExit(f"ingestion failed for {document['filename']}: {status}")
            print(f"ready: {document['filename']}")

        imported = client.post(
            "/evaluations/datasets/import",
            json={
                "name": args.dataset_name,
                "description": bundle.get("description", ""),
                "kb_id": kb["id"],
                "bundle": bundle,
            },
            headers=headers,
        )
        imported.raise_for_status()
        dataset = imported.json()
        print(
            json.dumps(
                {
                    "kb_id": kb["id"],
                    "dataset_id": dataset["id"],
                    "documents": len(bundle["documents"]),
                    "questions": dataset["question_count"],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
