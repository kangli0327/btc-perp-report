from __future__ import annotations

import base64
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from nacl import encoding, public


ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / ".github-token.txt"
GIT = r"C:\Users\kangl\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"


def token() -> str:
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


def api(method: str, path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token()}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "btc-report-api-publisher",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {body}") from exc


def tracked_files() -> list[str]:
    out = subprocess.check_output([GIT, "ls-files", "-z"], cwd=ROOT)
    return [p.decode("utf-8") for p in out.split(b"\0") if p]


def current_head(owner: str, repo: str) -> str | None:
    try:
        ref = api("GET", f"/repos/{owner}/{repo}/git/ref/heads/main")
        return ref["object"]["sha"]
    except RuntimeError as exc:
        if " 404 " in str(exc) or "409" in str(exc):
            return None
        raise


def upload_tree(owner: str, repo: str) -> str:
    tree = []
    for rel in tracked_files():
        raw = (ROOT / rel).read_bytes()
        blob = api(
            "POST",
            f"/repos/{owner}/{repo}/git/blobs",
            {"content": base64.b64encode(raw).decode("ascii"), "encoding": "base64"},
        )
        tree.append({"path": rel.replace("\\", "/"), "mode": "100644", "type": "blob", "sha": blob["sha"]})
    tree_data = api("POST", f"/repos/{owner}/{repo}/git/trees", {"tree": tree})
    return tree_data["sha"]


def content_sha(owner: str, repo: str, rel: str) -> str | None:
    quoted_path = urllib.parse.quote(rel.replace("\\", "/"), safe="/")
    try:
        data = api("GET", f"/repos/{owner}/{repo}/contents/{quoted_path}?ref=main")
        return data.get("sha")
    except RuntimeError as exc:
        if "404" in str(exc) or "409" in str(exc):
            return None
        raise


def publish_contents(owner: str, repo: str) -> None:
    for rel in tracked_files():
        raw = (ROOT / rel).read_bytes()
        path = urllib.parse.quote(rel.replace("\\", "/"), safe="/")
        payload = {
            "message": f"Publish {rel}",
            "content": base64.b64encode(raw).decode("ascii"),
            "branch": "main",
        }
        sha = content_sha(owner, repo, rel)
        if sha:
            payload["sha"] = sha
        api("PUT", f"/repos/{owner}/{repo}/contents/{path}", payload)


def publish_commit(owner: str, repo: str) -> None:
    head = current_head(owner, repo)
    if not head:
        publish_contents(owner, repo)
        return
    tree_sha = upload_tree(owner, repo)
    payload = {"message": "Publish BTC perpetual report site", "tree": tree_sha, "parents": [head]}
    commit = api("POST", f"/repos/{owner}/{repo}/git/commits", payload)
    api("PATCH", f"/repos/{owner}/{repo}/git/refs/heads/main", {"sha": commit["sha"], "force": True})


def put_secret(owner: str, repo: str, name: str, value: str) -> None:
    key_data = api("GET", f"/repos/{owner}/{repo}/actions/secrets/public-key")
    public_key = public.PublicKey(key_data["key"].encode("utf-8"), encoding.Base64Encoder())
    encrypted = public.SealedBox(public_key).encrypt(value.encode("utf-8"), encoder=encoding.Base64Encoder()).decode("utf-8")
    api(
        "PUT",
        f"/repos/{owner}/{repo}/actions/secrets/{urllib.parse.quote(name)}",
        {"encrypted_value": encrypted, "key_id": key_data["key_id"]},
    )


def enable_pages(owner: str, repo: str) -> None:
    try:
        api("POST", f"/repos/{owner}/{repo}/pages", {"build_type": "workflow"})
    except RuntimeError as exc:
        if "409" not in str(exc) and "already exists" not in str(exc):
            raise


def main() -> None:
    repo = "btc-perp-report"
    owner = api("GET", "/user")["login"]
    try:
        api("GET", f"/repos/{owner}/{repo}")
    except RuntimeError:
        api(
            "POST",
            "/user/repos",
            {
                "name": repo,
                "private": False,
                "description": "BTC-USDT perpetual futures 4-hour decision report",
                "auto_init": False,
            },
        )
    publish_commit(owner, repo)
    enable_pages(owner, repo)
    print(json.dumps({"repo": f"https://github.com/{owner}/{repo}", "pages": f"https://{owner}.github.io/{repo}/"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
