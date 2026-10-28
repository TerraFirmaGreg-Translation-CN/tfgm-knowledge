"""Resolve releases and download selected files through sparse Git checkouts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def request(url):
    headers = {"User-Agent": "tfgm-knowledge/0.1", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = "Bearer " + token
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=headers), timeout=60) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def api(path):
    return json.loads(request("https://api.github.com/" + path))


def raw(repository, commit, path):
    return request(f"https://raw.githubusercontent.com/{repository}/{commit}/{quote(path)}")


def dependencies(pakku, platform):
    result = []
    for project in pakku["projects"]:
        files = [f for f in project.get("files", []) if f.get("type") == platform]
        # Do not silently substitute another platform's possibly different version.
        result.append({
            "id": project["pakku_id"], "name": project.get("name", {}),
            "slug": project.get("slug", {}), "type": project.get("type"),
            "platform": platform, "files": files,
            "status": "locked" if files else "unavailable-on-selected-platform",
        })
    return result


def core_tag(pakku, platform):
    names = [f["file_name"] for p in pakku["projects"] for f in p.get("files", [])
             if f.get("type") == platform and
             f["file_name"].startswith("TerraFirmaGreg-Core-Modern-")]
    versions = {re.fullmatch(r"TerraFirmaGreg-Core-Modern-(.+)\.jar", n)[1] for n in names}
    if len(versions) != 1:
        raise ValueError(f"Expected one Core-Modern version for {platform}, got {versions}")
    return versions.pop()


def validate_config(config):
    ids = set()
    for source in config["sources"]:
        if not re.fullmatch(r"[a-z0-9-]+", source["id"]) or source["id"] in ids:
            raise ValueError("Invalid or duplicate source id")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source["repository"]):
            raise ValueError("Invalid repository")
        if any(".." in p.split("/") for p in source["include"]):
            raise ValueError("Unsafe source pattern")
        ids.add(source["id"])


def resolve(config, version="latest"):
    validate_config(config)
    repo = next(s["repository"] for s in config["sources"] if s["id"] == "modpack")
    release = api(f"repos/{repo}/releases/" + ("latest" if version == "latest" else "tags/" + quote(version, safe="")))
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("Only published stable releases are supported")
    tag = release["tag_name"]
    mod_commit = api(f"repos/{repo}/commits/{quote(tag, safe='')}")["sha"]
    pakku = json.loads(raw(repo, mod_commit, "pakku-lock.json"))
    core = core_tag(pakku, config["platform"])

    def resolve_one(source):
        policy = source["ref_policy"]
        ref = tag if policy == "release" else core if policy == "dependency" else policy
        repository = source["repository"]
        commit = mod_commit if source["id"] == "modpack" else api(f"repos/{repository}/commits/{quote(ref, safe='')}")["sha"]
        meta = api(f"repos/{repository}")
        return {**source, "ref": ref, "commit": commit,
                "license": (meta.get("license") or {}).get("spdx_id") or "NOASSERTION",
                "version_relation": "release-matched" if policy in ("release", "dependency") else "unversioned-snapshot"}

    with ThreadPoolExecutor(max_workers=4) as pool:
        sources = list(pool.map(resolve_one, config["sources"]))
    exports = []
    for name in ("recipe-book", "quest-book", "field-guide"):
        url = f"https://wiki.terrafirmagreg.team/modern/{name}/build.json"
        try:
            data = json.loads(request(url))
            exports.append({"id": name, "url": url, "build": data,
                            "status": "version-matched" if data.get("modpack") == tag else "version-mismatch"})
        except (OSError, ValueError) as exc:
            exports.append({"id": name, "url": url, "status": "unavailable", "error": str(exc)})
    return {"schema_version": 1, "resolved_at": datetime.now(timezone.utc).isoformat(),
            "config_sha256": digest(config), "modpack_version": tag,
            "minecraft_versions": pakku["mc_versions"], "platform": config["platform"],
            "languages": config["languages"], "sources": sources,
            "dependencies": dependencies(pakku, config["platform"]), "exports": exports,
            "release": {"url": release["html_url"], "published_at": release["published_at"], "body": release.get("body") or ""}}


def git(path, *args, input=None):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
    proc = subprocess.run(["git", "-C", str(path), *args], input=input,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          env=env, timeout=600)
    if proc.returncode:
        raise RuntimeError(f"Git {args[0]} failed: {proc.stderr.strip()}")
    return proc.stdout


def snapshot_path(cache, source):
    # Include pattern hash: changing selection must never reuse an older sparse tree.
    return Path(cache) / source["id"] / (source["commit"] + "-" + digest(source["include"])[:12])


def verify_snapshot(path, source):
    if git(path, "rev-parse", "HEAD").strip() != source["commit"]:
        raise ValueError(f"Wrong snapshot commit: {source['id']}")
    if git(path, "status", "--porcelain", "--untracked-files=all").strip():
        raise ValueError(f"Modified source snapshot: {source['id']}; remove cache and sync again")


def sync_one(cache, source):
    path = snapshot_path(cache, source)
    marker = path.parent / (path.name + ".ready")
    if marker.exists():
        verify_snapshot(path, source)
        return source["id"], "cached"
    path.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").exists():
        git(path, "init", "--quiet")
        git(path, "remote", "add", "origin", f"https://github.com/{source['repository']}.git")
    # Set sparse paths BEFORE checkout, so models/textures are not downloaded.
    git(path, "config", "remote.origin.promisor", "true")
    git(path, "config", "remote.origin.partialclonefilter", "blob:none")
    git(path, "sparse-checkout", "set", "--no-cone", "--stdin", input="\n".join(source["include"]) + "\n")
    git(path, "fetch", "--quiet", "--filter=blob:none", "--depth=1", "origin", source["commit"])
    git(path, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", "FETCH_HEAD")
    verify_snapshot(path, source)
    marker.touch()
    return source["id"], "downloaded"


def sync(lock, cache):
    with ThreadPoolExecutor(max_workers=3) as pool:
        # Any required-source failure aborts the build; old bundles remain intact.
        for name, status in pool.map(lambda s: sync_one(cache, s), lock["sources"]):
            print(f"{name}: {status}", flush=True)
