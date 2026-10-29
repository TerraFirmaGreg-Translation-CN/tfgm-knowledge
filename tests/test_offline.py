import io
import json
from pathlib import Path
import socket
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tfgm_knowledge.offline import build, Knowledge, verify, file_sha
from tfgm_knowledge.player_pack import encoded


class OfflineTests(unittest.TestCase):
    def fixture(self, root, count=1, unsafe=False):
        recipe={'schema':1,'id':'tfg:test','category':'tfc:instant_barrel','widgets':[{'role':'input','interaction':{'kind':'item','id':'tfc:flux'}},{'role':'output','interaction':{'kind':'fluid','id':'tfc:limewater','amountMb':500}}]}
        prefix='bundles/tfg-0.13.15/'
        files={'build.json':encoded({'modpack':'0.13.15','releaseTag':'test'}),prefix+'bundle.json':encoded({'schema':2,'recipeCount':count}),prefix+'items/index.json':encoded({'schema':1,'tfc':['limewater']}),prefix+'items-lang/zh_cn.json':encoded({'items':[{'id':'tfc:limewater','label':'石灰水'}]}),prefix+'recipes/tfg/test.json':encoded(recipe),prefix+'recipes/tfg/test.png':b'\x89PNG\r\n\x1a\nimage',prefix+'items/tfc/limewater.json':encoded({'schema':2,'outputs':{'tfc:instant_barrel':['tfg:test']}})}
        if unsafe:files['../escape']=b'no'
        archive=root/'source.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            for name,value in files.items():
                member=tarfile.TarInfo('./'+name);member.size=len(value);tar.addfile(member,io.BytesIO(value))
        source=root/'source.json';source.write_bytes(encoded({'game_version':'0.13.15','release_tag':'test','sha256':file_sha(archive),'url':'https://example.org/source'}))
        return archive,source

    def test_full_library_with_network_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,source=self.fixture(root)
            with patch.object(socket.socket,'connect',side_effect=AssertionError('Network prohibited')):
                folder,manifest=build(archive,source,root/'kb')
                self.assertTrue(verify(folder)['verified'])
                kb=Knowledge(folder,'0.13.15')
                try:
                    self.assertEqual(len(kb.search('石灰水')['results']),1)
                    self.assertEqual(len(kb.search('石灰')['results']),1)
                    self.assertEqual(kb.items('石灰水')['items'][0]['id'],'tfc:limewater')
                    self.assertEqual(kb.find('tfc:limewater')['total'],1)
                    result=kb.recipe('tfg:test');self.assertNotIn('amount',result['inputs'][0]['interaction'])
                    kb.asset(result['image_resource'],root/'image.png');self.assertTrue((root/'image.png').is_file())
                    with self.assertRaises(ValueError):kb.recipe('missing:id')
                finally:kb.close()
                with self.assertRaises(ValueError):Knowledge(folder,'0.13.17')
                with (folder/'documents.jsonl').open() as stream:self.assertEqual(sum(1 for _ in stream),1)
            with (folder/'knowledge.sqlite').open('ab') as f:f.write(b'tamper')
            with self.assertRaisesRegex(ValueError,'校验失败'):verify(folder)

    def test_incomplete_or_unsafe_bundle_is_not_published(self):
        for mismatch,unsafe in [(2,False),(1,True)]:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);archive,source=self.fixture(root,mismatch,unsafe)
                with self.assertRaises(ValueError):build(archive,source,root/'kb')
                self.assertFalse((root/'kb').exists())
                self.assertFalse(list(root.glob('.offline-build-*')))

    def test_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,source=self.fixture(root);archive.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'SHA256'):build(archive,source,root/'kb')

    def test_ragflow_export_and_portable_archive(self):
        from tfgm_knowledge.offline import export_ragflow,pack,unpack
        from tfgm_knowledge.ingest import load_pack
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,source=self.fixture(root);folder,_=build(archive,source,root/'kb')
            result=export_ragflow(folder,'0.13.15',root/'shards',batch_size=1)
            self.assertEqual(result['documents'],1)
            manifest,documents=load_pack(str(root/'shards/tfgm-0.13.15-r100/manifest.json'))
            self.assertEqual(len(documents),1)
            self.assertIn('导出未注明数量',next(iter(documents.values())).decode())
            receipt=pack(folder,root/'portable.zip');self.assertEqual(file_sha(root/'portable.zip'),receipt['sha256'])
            installed=unpack(root/'portable.zip',root/'portable.zip.json',root/'installed')
            self.assertTrue(installed['verified'])
            with zipfile.ZipFile(root/'portable.zip') as z:
                self.assertEqual(set(z.namelist()),{'manifest.json','knowledge.sqlite','documents.jsonl'})
