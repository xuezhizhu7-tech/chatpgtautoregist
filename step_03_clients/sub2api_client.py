#!/usr/bin/env python3
"""
Sub2API client: login, generate auth URL, exchange code, create account.
"""
import json, subprocess
from step_01_config.config import SUB2API, SUB2API_EMAIL, SUB2API_PASS
from step_02_shared.records import log


def sub2api_request(method, path, token=None, data=None):
    """Helper for Sub2API API calls"""
    cmd = ["curl", "-sS", "--max-time", "15", "-X", method]
    if token:
        cmd += ["-H", f"Authorization: Bearer {token}"]
    cmd += ["-H", "Content-Type: application/json"]
    if data:
        cmd += ["-d", json.dumps(data)]
    cmd.append(f"{SUB2API}{path}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(r.stdout)


def sub2api_login():
    resp = sub2api_request("POST", "/api/v1/auth/login",
        data={"email": SUB2API_EMAIL, "password": SUB2API_PASS})
    return resp["data"]["access_token"]


def generate_auth_url(token):
    resp = sub2api_request("POST", "/api/v1/admin/openai/generate-auth-url",
        token=token, data={"redirect_uri": "http://localhost:1455/auth/callback"})
    data = resp["data"]
    return data["auth_url"], data["session_id"], data.get("state", "")
