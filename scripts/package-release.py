"""Build a credential-free deployment ZIP from an explicit file allowlist."""
from pathlib import Path
import zipfile
import subprocess

root = Path(__file__).resolve().parent.parent
version = 'v0.1.0'
output = root / 'dist/releases' / version
output.mkdir(parents=True, exist_ok=True)
# The release compose consumes an image; it must not reference a source build context.
compose = (root/'compose.mcp.yaml').read_text()
compose = compose.replace('    build:\n      context: .\n      dockerfile: Dockerfile.mcp\n', '')
compose = compose.replace('tfgm-knowledge-mcp:local', f'tfgm-knowledge-mcp:{version}')
files = {
    'prepare.sh': root/'deploy/release/prepare.sh',
    'download-knowledge.sh': root/'deploy/release/download-knowledge.sh',
    'README.md': root/'deploy/release/README.md',
    'DATA-SOURCES.md': root/'deploy/release/DATA-SOURCES.md',
    'LICENSE': root/'LICENSE',
    'ragflow.example.json': root/'deploy/ragflow.example.json',
}
prefix = f'tfgm-mcp-{version}/'
with zipfile.ZipFile(output/f'tfgm-mcp-{version}-deploy.zip', 'w', compression=zipfile.ZIP_DEFLATED) as z:
    for name, path in files.items():
        z.write(path, prefix+name)
    z.writestr(prefix+'compose.yaml', compose)
    z.writestr(prefix+'SOURCE_COMMIT', subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True))
print(output/f'tfgm-mcp-{version}-deploy.zip')
