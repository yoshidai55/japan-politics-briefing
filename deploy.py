"""
日本政治ブリーフィング ― GitHub Pages 自動デプロイ
deploy_to_github.ps1 から PAT を読み取り、当ディレクトリ内の
.html / .md / .py ファイルを GitHub リポジトリにプッシュします。

使い方:
  python deploy.py                # 変更のあったファイルだけアップロード
  python deploy.py --all          # 全ファイルを強制再アップロード
  python deploy.py --dry-run      # アップロードはせず対象ファイルを表示
"""
import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

USERNAME = "yoshidai55"
REPO = "japan-politics-briefing"
BRANCH = "main"
INCLUDE_EXT = {".html", ".md", ".py"}
# このファイル自身は機密を含まないが、deploy_to_github.ps1 と
# その関連スクリプトは PAT を含むためアップロードしない
EXCLUDE_FILES = {"deploy_to_github.ps1", "GitHubにアップロード.bat", "run_deploy.bat"}


def read_pat(script_dir):
    """deploy_to_github.ps1 から PAT を抽出する"""
    ps1 = os.path.join(script_dir, "deploy_to_github.ps1")
    if not os.path.exists(ps1):
        raise SystemExit("ERROR: deploy_to_github.ps1 が見つかりません。PAT を取得できません。")
    with open(ps1, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    m = re.search(r'\$PAT\s*=\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("ERROR: deploy_to_github.ps1 から PAT を抽出できませんでした。")
    return m.group(1)


def api(method, url, headers, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", errors="replace")}


def git_blob_sha(data_bytes):
    """GitHub の blob SHA を算出（差分判定用）"""
    h = hashlib.sha1()
    header = f"blob {len(data_bytes)}\0".encode("utf-8")
    h.update(header)
    h.update(data_bytes)
    return h.hexdigest()


def main():
    args = sys.argv[1:]
    force_all = "--all" in args
    dry_run = "--dry-run" in args

    script_dir = os.path.dirname(os.path.abspath(__file__))
    pat = read_pat(script_dir)

    headers = {
        "Authorization": f"token {pat}",
        "User-Agent": "japan-politics-deploy",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }

    # 認証確認
    code, user = api("GET", "https://api.github.com/user", headers)
    if code != 200:
        raise SystemExit(f"ERROR: GitHub 認証に失敗: HTTP {code} / {user}")
    print(f"OK 認証: {user.get('login')}")

    # 対象ファイル一覧
    targets = []
    for name in sorted(os.listdir(script_dir)):
        p = os.path.join(script_dir, name)
        if not os.path.isfile(p):
            continue
        if name in EXCLUDE_FILES:
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in INCLUDE_EXT:
            continue
        targets.append((name, p))

    print(f"対象: {len(targets)} ファイル ({'強制再UP' if force_all else '差分のみ'}{', DRY-RUN' if dry_run else ''})")

    if dry_run:
        for name, _ in targets:
            print(f"  -> {name}")
        return

    ok = ng = skip = 0
    for name, path in targets:
        with open(path, "rb") as f:
            data = f.read()
        local_sha = git_blob_sha(data)

        url = f"https://api.github.com/repos/{USERNAME}/{REPO}/contents/{urllib.parse.quote(name)}"
        # 既存ファイルの SHA を取得
        code, info = api("GET", f"{url}?ref={BRANCH}", headers)
        remote_sha = info.get("sha") if isinstance(info, dict) and code == 200 else None
        remote_blob_sha = None
        if isinstance(info, dict) and code == 200:
            # contents API の "sha" は blob SHA と同じ
            remote_blob_sha = info.get("sha")

        if not force_all and remote_blob_sha == local_sha:
            print(f"  SKIP (no change): {name}")
            skip += 1
            continue

        body = {
            "message": f"update {name}",
            "content": base64.b64encode(data).decode("ascii"),
            "branch": BRANCH,
        }
        if remote_sha:
            body["sha"] = remote_sha

        code, resp = api("PUT", url, headers, body)
        if code in (200, 201):
            print(f"  OK : {name}")
            ok += 1
        else:
            msg = resp.get("message") if isinstance(resp, dict) else str(resp)
            print(f"  NG : {name}  HTTP {code} / {msg}")
            ng += 1
        # rate limit を緩める軽い間隔
        time.sleep(0.15)

    print(f"完了: OK={ok}  NG={ng}  SKIP={skip}")
    print(f"URL: https://{USERNAME}.github.io/{REPO}/")

    if ng:
        sys.exit(2)


if __name__ == "__main__":
    # urllib.parse は遅延 import
    import urllib.parse  # noqa
    main()
