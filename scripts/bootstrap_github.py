from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from nacl import encoding, public


ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / ".github-token.txt"
POSITION_EXAMPLE = ROOT / "config" / "position.example.json"
PREFERENCE_EXAMPLE = ROOT / "config" / "preference.example.json"


def read_token() -> str:
    if not TOKEN_FILE.exists():
        raise SystemExit(f"Missing token file: {TOKEN_FILE}")
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("Token file is empty.")
    return token


def request_json(method: str, path: str, token: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "btc-report-bootstrap",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GitHub API {method} {path} failed: {exc.code} {body}") from exc


def get_or_create_repo(token: str, repo_name: str, private: bool) -> dict:
    user = request_json("GET", "/user", token)
    owner = user["login"]
    try:
        return request_json("GET", f"/repos/{owner}/{repo_name}", token)
    except SystemExit as exc:
        if " 404 " not in str(exc):
            raise
    return request_json(
        "POST",
        "/user/repos",
        token,
        {
            "name": repo_name,
            "private": private,
            "description": "BTC-USDT perpetual futures 4-hour decision report",
            "auto_init": False,
        },
    )


def put_secret(token: str, owner: str, repo: str, name: str, value: str) -> None:
    key_data = request_json("GET", f"/repos/{owner}/{repo}/actions/secrets/public-key", token)
    public_key = public.PublicKey(key_data["key"].encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(value.encode("utf-8"), encoder=encoding.Base64Encoder()).decode("utf-8")
    request_json(
        "PUT",
        f"/repos/{owner}/{repo}/actions/secrets/{urllib.parse.quote(name)}",
        token,
        {"encrypted_value": encrypted, "key_id": key_data["key_id"]},
    )


def run_git(args: list[str], token: str | None = None) -> None:
    git = r"C:\Users\kangl\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"
    cmd = [git]
    if token:
        auth = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
        cmd += ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {auth}"]
    cmd += args
    subprocess.run(cmd, cwd=ROOT, check=True)


def enable_pages(token: str, owner: str, repo: str) -> None:
    try:
        request_json("POST", f"/repos/{owner}/{repo}/pages", token, {"build_type": "workflow"})
    except SystemExit as exc:
        message = str(exc)
        if "already exists" not in message and "409" not in message:
            raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="btc-perp-report")
    parser.add_argument("--private", action="store_true")
    parser.add_argument("--position-json", default=str(POSITION_EXAMPLE))
    parser.add_argument("--preference-json", default=str(PREFERENCE_EXAMPLE))
    args = parser.parse_args()

    token = read_token()
    repo_data = get_or_create_repo(token, args.repo, args.private)
    owner = repo_data["owner"]["login"]
    repo = repo_data["name"]
    clone_url = repo_data["clone_url"]

    try:
        run_git(["remote", "add", "origin", clone_url])
    except subprocess.CalledProcessError:
        run_git(["remote", "set-url", "origin", clone_url])

    run_git(["push", "-u", "origin", "main"], token=token)

    position_json = Path(args.position_json).read_text(encoding="utf-8")
    preference_json = Path(args.preference_json).read_text(encoding="utf-8")
    put_secret(token, owner, repo, "POSITION_CONFIG_JSON", position_json)
    put_secret(token, owner, repo, "PREFERENCE_CONFIG_JSON", preference_json)
    enable_pages(token, owner, repo)

    print(json.dumps({
        "repo": f"https://github.com/{owner}/{repo}",
        "pages": f"https://{owner}.github.io/{repo}/",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
