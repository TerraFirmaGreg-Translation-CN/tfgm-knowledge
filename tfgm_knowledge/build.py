"""Normalize pinned source files and atomically produce offline knowledge bundles."""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from urllib.parse import quote
import zipfile

from . import __version__, snbt
from .sources import canonical, digest, snapshot_path, verify_snapshot, write_json


TEXT_EXTENSIONS = {".md", ".mdx", ".json", ".snbt", ".toml", ".js", ".java", ".mjs", ".yml", ".yaml", ".env", ".sh"}
LOCALE = re.compile(r"(?:^|/)([a-z]{2}_[a-z]{2})(?:/|\.)")
TRANSLATION = re.compile(r"\{([\w.-]+)\}")


def locale_of(path):
    match = LOCALE.search(path)
    return match[1] if match else "und"


def strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]
    return []


def readable(text):
    text = text.replace("$(br2)", "\n\n").replace("$(br)", "\n")
    text = re.sub(r"\$\(li\d*\)", "\n- ", text)
    # Keep the raw page object separately: recipe ids, anchors and multiblocks
    # must not be lost when formatting codes are removed from searchable prose.
    return re.sub(r"\$\([^)]*\)", "", text)


def localize(value, language, translations, fallbacks=None, missing=None):
    if isinstance(value, str):
        def replace(match):
            key = match[1]
            current = translations.get(language, {}).get(key)
            if current is not None:
                return str(current)
            english = translations.get("en_us", {}).get(key)
            if english is not None:
                if fallbacks is not None:
                    fallbacks.add(key)
                return str(english)
            if missing is not None:
                missing.add(key)
            return match[0]
        return TRANSLATION.sub(replace, value)
    if isinstance(value, list):
        return [localize(v, language, translations, fallbacks, missing) for v in value]
    if isinstance(value, dict):
        return {k: localize(v, language, translations, fallbacks, missing) for k, v in value.items()}
    return value


def chunks(text, size=1800, overlap=160):
    if size <= overlap or overlap < 0:
        raise ValueError("Invalid chunk size/overlap")
    pos = 0
    while pos < len(text):
        end = min(pos + size, len(text))
        if end < len(text):
            boundary = text.rfind("\n", pos + size // 2, end)
            if boundary > pos:
                end = boundary
        yield pos, end, text[pos:end]
        if end == len(text):
            break
        pos = end - overlap


def collect_files(lock, cache):
    files = []
    for source in lock["sources"]:
        root = snapshot_path(cache, source)
        verify_snapshot(root, source)
        for directory, dirs, names in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d != ".git" and not (Path(directory) / d).is_symlink())
            for name in sorted(names):
                path = Path(directory) / name
                if path.is_symlink() or not path.is_file():
                    continue
                relative = path.relative_to(root).as_posix()
                if path.suffix not in TEXT_EXTENSIONS and not name.startswith(("LICENSE", "COPYING", "NOTICE")):
                    continue
                lang = locale_of(relative)
                if lang != "und" and lang not in lock["languages"]:
                    continue
                # Shader/model binaries are excluded by sparse selection and type.
                if path.stat().st_size > 16 * 1024 * 1024:
                    raise ValueError(f"Source text exceeds 16 MiB: {relative}")
                text = path.read_text(encoding="utf-8-sig")
                files.append((source, relative, text))
    return files


def translations_from(files):
    maps = {}
    provenance = {}
    # Resource pack text overrides mod resources. Split TFG language files are
    # loaded after root locale files; retain source paths used to resolve keys.
    order = sorted(files, key=lambda f: (f[0]["id"] == "modpack", f[1]))
    for source, path, text in order:
        if "/lang/" not in path or not path.endswith(".json"):
            continue
        lang = locale_of(path)
        if lang == "und":
            continue
        data = json.loads(text)
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            if isinstance(value, str):
                maps.setdefault(lang, {})[key] = value
                provenance.setdefault(lang, {})[key] = {"source": source["id"], "path": path, "commit": source["commit"]}
    return maps, provenance


def base_record(lock, source, path, key, kind, title, text, language="und", data=None):
    identity = f"{source['id']}:{path}:{key}:{language}"
    return {"id": hashlib.sha256(identity.encode()).hexdigest()[:24],
            "kind": kind, "title": title, "text": text, "language": language,
            "source_id": source["id"], "source_path": path,
            "source_url": f"https://github.com/{source['repository']}/blob/{source['commit']}/{quote(path)}",
            "commit": source["commit"], "license": source["license"],
            "context_modpack_version": lock["modpack_version"],
            "applicable_modpack_version": lock["modpack_version"] if source["version_relation"] == "release-matched" else None,
            "version_relation": source["version_relation"],
            "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "data": data}


def quest_records(lock, source, path, chapter, translations, provenance):
    for quest in chapter.get("quests", []):
        for lang in lock["languages"]:
            fallback, missing = set(), set()
            localized = localize(quest, lang, translations, fallback, missing)
            title = localized.get("title")
            if not title:
                for task in localized.get("tasks", []):
                    item = task.get("item", "")
                    if isinstance(item, dict):
                        item = item.get("id", "")
                    title = task.get("title")
                    if not title and isinstance(item, str) and ":" in item:
                        namespace, name = item.split(":", 1)
                        keys = [f"{prefix}.{namespace}.{name.replace('/', '.')}" for prefix in ("item", "block")]
                        title = next((translations.get(lang, {}).get(k) for k in keys if translations.get(lang, {}).get(k)), item)
                    if title:
                        break
            title = title or quest["id"]
            title = str(title)
            text = "\n\n".join([title, str(localized.get("subtitle", "")),
                                  "\n".join(strings(localized.get("description", []))),
                                  "Tasks: " + canonical(localized.get("tasks", [])),
                                  "Rewards: " + canonical(localized.get("rewards", []))])
            keys = set(TRANSLATION.findall(canonical(quest)))
            refs = []
            for key in sorted(keys):
                used_language = "en_us" if key in fallback else lang
                ref = provenance.get(used_language, {}).get(key)
                if ref:
                    refs.append({"key": key, "language": used_language, **ref})
            data = {"quest_id": quest["id"], "chapter_id": chapter["id"],
                    "chapter_file": chapter.get("filename"),
                    "dependencies": quest.get("dependencies", []),
                    "raw": quest, "localized": localized,
                    "translation_fallbacks": sorted(fallback), "missing_translation_keys": sorted(missing),
                    "translation_sources": refs}
            yield base_record(lock, source, path, quest["id"], "quest", title, text, lang, data)


def records_from(lock, files):
    translations, provenance = translations_from(files)
    records = []
    warnings = []
    for source, path, text in files:
        lang = locale_of(path)
        suffix = Path(path).suffix
        if "/quests/chapters/" in path and suffix == ".snbt":
            chapter = snbt.loads(text)
            records.extend(quest_records(lock, source, path, chapter, translations, provenance))
            records.append(base_record(lock, source, path, "chapter", "quest-chapter",
                                       chapter.get("filename", path), text, "und",
                                       {k: v for k, v in chapter.items() if k != "quests"}))
            continue
        data = None
        kind = "source-code"
        title = path
        body = text
        if suffix in (".md", ".mdx"):
            kind = "document"
            match = re.search(r"^#\s+(.+)", text, re.M)
            title = match[1] if match else path
        elif suffix == ".json":
            try:
                data = json.loads(text)
            except ValueError as exc:
                warnings.append({"path": path, "source": source["id"], "reason": "invalid-json", "detail": str(exc)})
                kind = "unparsed-data"
            else:
                kind = "data"
                if "/patchouli_books/" in path:
                    kind = "field-guide"
                    if isinstance(data, dict):
                        title = str(data.get("name", path))
                        body = title + "\n\n" + readable("\n\n".join(strings(data)))
                elif "/lang/" in path:
                    kind = "language"
                elif "/recipes/" in path:
                    kind = "recipe-definition"
                elif "/tags/" in path:
                    kind = "tag-definition"
        elif suffix in (".toml", ".snbt", ".env"):
            kind = "configuration"
        if source["role"] == "export-tool":
            kind = "export-tool"
        records.append(base_record(lock, source, path, "file", kind, title, body, lang, data))
    source = next(s for s in lock["sources"] if s["id"] == "modpack")
    release_record = base_record(lock, source, "@release", lock["modpack_version"], "release",
                                 lock["modpack_version"], lock["release"]["body"], "en_us")
    release_record["source_url"] = lock["release"]["url"]
    records.append(release_record)
    return records, warnings


def validate_quests(records):
    quests = [r for r in records if r["kind"] == "quest" and r["language"] == "en_us"]
    ids = [r["data"]["quest_id"] for r in quests]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate quest ids")
    # FTB allows dependencies on chapters; don't assume every edge targets a quest.
    known = set(ids) | {r["data"]["id"] for r in records if r["kind"] == "quest-chapter"}
    return [{"quest_id": r["data"]["quest_id"], "dependency": dep, "reason": "unresolved-dependency"}
            for r in quests for dep in r["data"]["dependencies"] if dep not in known]


def create_database(path, records):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT, language TEXT, title TEXT, source_url TEXT, payload TEXT)")
        db.execute("CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED, title, text, tokenize='trigram')")
        db.execute("CREATE TABLE quest_edges (quest_id TEXT, dependency_id TEXT, PRIMARY KEY(quest_id, dependency_id))")
        for row in records:
            db.execute("INSERT INTO records VALUES (?,?,?,?,?,?)", (row["id"], row["kind"], row["language"], row["title"], row["source_url"], canonical(row)))
            db.execute("INSERT INTO search VALUES (?,?,?)", (row["id"], row["title"], row["text"]))
            if row["kind"] == "quest":
                db.executemany("INSERT OR IGNORE INTO quest_edges VALUES (?,?)",
                               [(row["data"]["quest_id"], dep) for dep in row["data"]["dependencies"]])
        result = db.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise ValueError(f"SQLite integrity check failed: {result}")


def search(path, query, limit=10, kind=None, language=None):
    if not query.strip():
        raise ValueError("Search query cannot be empty")
    with sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True) as db:
        conditions, params = [], []
        if len(query) >= 3:
            conditions.append("search MATCH ?")
            params.append('"' + query.replace('"', '""') + '"')
            order = "ORDER BY bm25(search)"
        else:
            # Trigram FTS cannot match one/two-character Chinese queries.
            conditions.append("instr(search.title, ?) > 0 OR instr(search.text, ?) > 0")
            params.extend([query, query])
            order = "ORDER BY r.id"
        for field, value in (("kind", kind), ("language", language)):
            if value:
                conditions.append(f"r.{field} = ?")
                params.append(value)
        sql = "SELECT r.payload FROM search JOIN records r ON r.id=search.id WHERE "
        sql += " AND ".join("(" + c + ")" for c in conditions) + f" {order} LIMIT ?"
        params.append(limit)
        return [json.loads(row[0]) for row in db.execute(sql, params)]


def build(lock, cache, output):
    files = collect_files(lock, cache)
    records, warnings = records_from(lock, files)
    if not records or not any(r["kind"] == "quest" for r in records) or not any(r["kind"] == "field-guide" for r in records):
        raise ValueError("Required quest or field-guide content is missing")
    ids = [r["id"] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate record ids")
    warnings.extend(validate_quests(records))
    implementation = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob("*.py"))}
    build_key = digest({"version": __version__, "implementation": implementation, "sources": lock["sources"], "exports": lock["exports"],
                        "config": lock["config_sha256"], "release": lock["release"]})[:16]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"tfgm-{lock['modpack_version']}-{build_key}"
    archive = output / (destination.name + ".zip")
    if destination.exists() and archive.exists():
        write_json(output / "latest.json", {"directory": destination.name, "archive": archive.name,
                                            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()})
        return destination, archive, True
    staging = Path(tempfile.mkdtemp(prefix=".build-", dir=output))
    try:
        inventory = []
        for source, path, text in files:
            target = staging / "raw" / source["id"] / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            inventory.append({"source": source["id"], "path": path,
                              "sha256": hashlib.sha256(text.encode()).hexdigest()})
        chunk_count = 0
        with (staging / "records.jsonl").open("w", encoding="utf-8") as stream, (staging / "chunks.jsonl").open("w", encoding="utf-8") as chunk_stream:
            for row in records:
                stream.write(canonical(row) + "\n")
                for index, (start, end, text) in enumerate(chunks(row["text"])):
                    chunk_stream.write(canonical({k: v for k, v in row.items() if k not in ("data", "text")} |
                                                 {"id": f"{row['id']}:{index}", "record_id": row["id"], "text": text,
                                                  "char_start": start, "char_end": end}) + "\n")
                    chunk_count += 1
        docs = staging / "markdown"
        docs.mkdir()
        index_lines = [f"# TerraFirmaGreg Modern {lock['modpack_version']}\n", "原文、源码与运行时导出信息分别保留；未确认版本的 Wiki 内容不能视为本版本规则。\n"]
        for row in records:
            if row["kind"] not in ("document", "quest", "field-guide", "release"):
                continue
            name = row["id"] + ".md"
            title = row["title"].replace("\n", " ")
            (docs / name).write_text(f"# {title}\n\n来源：{row['source_url']}\n\n版本关系：{row['version_relation']}\n\n{row['text']}\n", encoding="utf-8")
            index_lines.append(f"- [{title.replace('[', '').replace(']', '')}]({name}) ({row['language']}, {row['kind']})")
        (docs / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
        create_database(staging / "knowledge.sqlite", records)
        write_json(staging / "sources.lock.json", lock)
        write_json(staging / "dependencies.json", lock["dependencies"])
        write_json(staging / "inventory.json", inventory)
        missing = sum(bool(r["data"]["missing_translation_keys"]) for r in records if r["kind"] == "quest")
        fallback = sum(bool(r["data"]["translation_fallbacks"]) for r in records if r["kind"] == "quest")
        report = {"warnings": warnings, "export_status": lock["exports"],
                  "quests_with_missing_translations": missing, "quests_with_english_fallback": fallback,
                  "missing_translations": [{"quest_id": r["data"]["quest_id"], "language": r["language"],
                                            "keys": r["data"]["missing_translation_keys"], "source_url": r["source_url"]}
                                           for r in records if r["kind"] == "quest" and r["data"]["missing_translation_keys"]],
                  "runtime_recipe_records": 0,
                  "limitations": ["Runtime EMI exports are inspected for version compatibility, not imported in v0.1.",
                                  "Source recipe definitions are not the final runtime recipe registry.",
                                  "Images and rendered multiblock previews are not bundled; raw references are retained."]}
        write_json(staging / "report.json", report)
        manifest = {"schema_version": 1, "tool_version": __version__, "build_id": build_key,
                    "implementation_sha256": digest(implementation),
                    "modpack_version": lock["modpack_version"], "resolved_at": lock["resolved_at"],
                    "source_count": len(lock["sources"]), "file_count": len(files),
                    "record_count": len(records), "chunk_count": chunk_count,
                    "counts_by_kind": dict(Counter(r["kind"] for r in records)),
                    "sources": [{k: v for k, v in s.items() if k != "include"} for s in lock["sources"]]}
        write_json(staging / "manifest.json", manifest)
        (staging / "NOTICE.md").write_text("# Upstream content\n\nThis bundle contains material from the pinned upstream sources in sources.lock.json. "
                                         "Upstream copyrights and licenses remain in force. The MIT license for the collector does not cover this material. "
                                         "NOASSERTION means a license was not identified; it does not grant redistribution rights. "
                                         "Included license files are preserved under raw/.\n", encoding="utf-8")
        # Only complete validated builds become visible; failed builds never
        # overwrite an older successful bundle or latest.json.
        temp_archive = output / ("." + destination.name + ".zip.tmp")
        with zipfile.ZipFile(temp_archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(staging))
        if destination.exists():
            raise ValueError(f"Incomplete existing build directory: {destination}")
        staging.rename(destination)
        temp_archive.replace(archive)
        write_json(output / "latest.json", {"directory": destination.name, "archive": archive.name,
                                            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()})
        return destination, archive, False
    finally:
        if staging.exists():
            shutil.rmtree(staging)
