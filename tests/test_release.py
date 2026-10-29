import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class ReleaseDownloadTest(unittest.TestCase):
    def test_download_verify_merge_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / 'remote'
            remote.mkdir()
            parts = [b'knowledge part zero', b'knowledge part one']
            checks = []
            for i, content in enumerate(parts):
                name = f'tfgm-library-r1.zip.part{i:03}'
                (remote / name).write_bytes(content)
                checks.append(f'{hashlib.sha256(content).hexdigest()}  {name}\n')
            checks.append(f'{hashlib.sha256(b"".join(parts)).hexdigest()}  tfgm-library-r1.zip\n')
            (remote / 'SHA256SUMS').write_text(''.join(checks))
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            curl = bin_dir / 'curl'
            curl.write_text('#!/usr/bin/env python3\nimport sys,os,pathlib,shutil\na=sys.argv[1:]\nu=next(x for x in a if x.startswith("https://"))\nshutil.copyfile(pathlib.Path(os.environ["FIXTURE_REMOTE"])/u.rsplit("/",1)[1],a[a.index("-o")+1])\n')
            curl.chmod(0o755)
            script = root / 'download-knowledge.sh'
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'deploy/release/download-knowledge.sh', script)
            env = {**os.environ, 'PATH': str(bin_dir)+os.pathsep+os.environ['PATH'], 'FIXTURE_REMOTE': str(remote)}
            def run():
                return subprocess.run(['bash', str(script)], env=env, capture_output=True, text=True)
            self.assertEqual(run().returncode, 0)
            self.assertEqual((root/'tfgm-library-r1.zip').read_bytes(), b''.join(parts))
            # A cached valid part must not require its remote source on a repeat run.
            (remote/'tfgm-library-r1.zip.part000').unlink()
            self.assertEqual(run().returncode, 0)
            # A bad downloaded part must not replace the verified merged archive.
            (root/'downloads/tfgm-library-r1.zip.part001').unlink()
            (remote/'tfgm-library-r1.zip.part001').write_bytes(b'corrupt')
            self.assertNotEqual(run().returncode, 0)
            self.assertEqual((root/'tfgm-library-r1.zip').read_bytes(), b''.join(parts))
