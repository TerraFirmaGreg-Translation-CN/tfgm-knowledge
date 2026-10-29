#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
base='https://github.com/TerraFirmaGreg-Translation-CN/tfgm-knowledge/releases/download/v0.1.0'
mkdir -p downloads
cd downloads
curl -fL --retry 3 "$base/SHA256SUMS" -o SHA256SUMS
parts=()
while read -r digest name; do
  [[ "$name" =~ ^tfgm-library-r1.zip.part[0-9]{3}$ ]] || continue
  parts+=("$name")
  if [[ -f "$name" ]] && printf '%s  %s\n' "$digest" "$name" | sha256sum -c --status; then continue; fi
  curl -fL --retry 3 "$base/$name" -o "$name.partial"
  printf '%s  %s\n' "$digest" "$name.partial" | sha256sum -c
  mv -- "$name.partial" "$name"
done < SHA256SUMS
[[ ${#parts[@]} -gt 0 ]] || { echo '校验清单缺少知识包分片' >&2; exit 1; }
cat -- "${parts[@]}" > tfgm-library-r1.zip.partial
expected=$(awk '$2=="tfgm-library-r1.zip" {print $1}' SHA256SUMS)
[[ "$expected" =~ ^[0-9a-f]{64}$ ]] || exit 1
printf '%s  %s\n' "$expected" tfgm-library-r1.zip.partial | sha256sum -c
mv tfgm-library-r1.zip.partial ../tfgm-library-r1.zip
printf '知识包已合并并校验。下一步：\nmkdir -p knowledge\nunzip tfgm-library-r1.zip -d knowledge\n'
