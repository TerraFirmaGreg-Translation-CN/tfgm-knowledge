import argparse
import json
from pathlib import Path
import sys

from .build import build, search
from .sources import digest, resolve, sync, validate_config, write_json


def main():
    parser = argparse.ArgumentParser(description="TFGM 一手资料知识库构建器")
    parser.add_argument("--config", default="sources/official.json")
    parser.add_argument("--lock", default="sources/lock.json")
    parser.add_argument("--cache", default=".cache/sources")
    parser.add_argument("--output", default="dist")
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("resolve", "update"):
        p = subs.add_parser(name, help="解析稳定版并锁定来源" if name == "resolve" else "检查更新、同步并构建")
        p.add_argument("--version", default="latest")
    subs.add_parser("sync", help="同步已锁定来源")
    subs.add_parser("build", help="离线构建知识库")
    subs.add_parser("validate", help="验证来源配置")
    p = subs.add_parser("search", help="离线搜索知识库")
    p.add_argument("query")
    p.add_argument("--database")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--kind")
    p.add_argument("--language")
    args = parser.parse_args()
    try:
        if args.command == "search":
            database = args.database
            if not database:
                latest = json.loads((Path(args.output) / "latest.json").read_text())
                database = Path(args.output) / latest["directory"] / "knowledge.sqlite"
            for row in search(database, args.query, args.limit, args.kind, args.language):
                print(json.dumps({k: row[k] for k in ("title", "kind", "language", "source_url", "applicable_modpack_version")}, ensure_ascii=False))
            return
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        validate_config(config)
        if args.command == "validate":
            print(f"Validated {len(config['sources'])} sources")
            return
        if args.command in ("resolve", "update"):
            lock = resolve(config, args.version)
            # Resolve to a complete lock in memory; failed builds keep last lock.
            if args.command == "resolve":
                write_json(args.lock, lock)
                print(f"Locked TerraFirmaGreg Modern {lock['modpack_version']}")
                return
        else:
            lock = json.loads(Path(args.lock).read_text(encoding="utf-8"))
            if lock["config_sha256"] != digest(config):
                raise ValueError("Source configuration changed; run resolve/update first")
        if args.command in ("sync", "update"):
            sync(lock, args.cache)
        if args.command in ("build", "update"):
            directory, archive, reused = build(lock, args.cache, args.output)
            print(f"{'Reused' if reused else 'Built'}: {directory}")
            print(f"Bundle: {archive}")
        if args.command == "update":
            write_json(args.lock, lock)
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
