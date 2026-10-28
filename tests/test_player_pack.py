import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from tfgm_knowledge.player_pack import build_pack, plain, sha
from tfgm_knowledge.ingest import validate_pack

class PlayerPackTests(unittest.TestCase):
    def fixture(self,root):
        root.mkdir();(root/'raw').mkdir()
        (root/'manifest.json').write_text(json.dumps({'modpack_version':'0.13.17','build_id':'test'}))
        (root/'sources.lock.json').write_text('{}');(root/'NOTICE.md').write_text('Upstream attribution')
        record={'id':'a','kind':'quest','language':'zh_cn','title':'&a测试','version_relation':'release-matched','source_id':'modpack','source_path':'quest.snbt','source_url':'https://example.org/source','commit':'a'*40,'license':'LGPL-3.0','applicable_modpack_version':'0.13.17','data':{'quest_id':'q1','chapter_file':'early','localized':{'description':['说明正文'],'tasks':[{'title':'矿石','count':2}]},'dependencies':[]}}
        excluded={**record,'id':'b','kind':'source-code','text':'secret implementation code'}
        (root/'records.jsonl').write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in [record,excluded]))
        return record

    def test_determinism_and_rewrite_protection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root/'source')
            p,m=build_pack(root/'source',root/'out')
            path=p/Path(m['archive']['url']).name
            original=path.read_bytes()
            self.assertEqual(len(m['documents']),1)
            _,again=build_pack(root/'source',root/'out')
            self.assertEqual(m,again);self.assertEqual(original,path.read_bytes())
            contents=validate_pack(m,original)
            text=contents['a'].decode();self.assertIn('任务要求数量：2',text);self.assertIn('来源：https://example.org/source',text)
            self.assertNotIn('&a',text);self.assertNotIn('implementation code',text)
            (root/'source'/'NOTICE.md').write_text('changed')
            with self.assertRaisesRegex(ValueError,'不可覆盖'):build_pack(root/'source',root/'out')
            self.assertEqual(original,path.read_bytes())

    def test_tamper_and_unsafe_archive_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root/'source');p,m=build_pack(root/'source',root/'out');blob=(p/Path(m['archive']['url']).name).read_bytes()
            with self.assertRaises(ValueError):validate_pack(m,blob+b'bad')
            output=io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(blob)) as source,zipfile.ZipFile(output,'w') as dest:
                for name in source.namelist():dest.writestr(name,source.read(name))
                dest.writestr('../escape','bad')
            modified=output.getvalue();m['archive'].update(size=len(modified),sha256=sha(modified))
            with self.assertRaisesRegex(ValueError,'不安全'):validate_pack(m,modified)

    def test_semantic_macros_keep_key_names(self):
        self.assertEqual(plain('$(tfg)中按$(k:key.use)$(br)$(thing)水$()'),'TerraFirmaGreg Modern中按使用键\n水')

    def test_import_resumes_without_duplicates(self):
        from unittest.mock import patch
        from tfgm_knowledge.ingest import import_pack
        class FakeClient:
            url='https://ragflow.local/api/v1'
            dataset=None
            docs=[]
            uploads=0
            def call(self,method,path,data=None):
                if method=='GET' and path.startswith('/datasets?'):return ([self.dataset] if self.dataset else []),None
                if method=='POST' and path=='/datasets':
                    self.dataset={**data,'id':'owned-dataset'};return self.dataset,None
                if method=='GET':return {'docs':self.docs,'total':len(self.docs)},None
                raise AssertionError((method,path))
            def upload(self,ds,name,content):
                self.uploads+=1;self.content=content
                d={'id':'doc1','name':name,'ingestion_status':'COMPLETED','chunk_count':1};self.docs.append(d);return [d]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root/'source');p,m=build_pack(root/'source',root/'out')
            config=root/'ragflow.json';config.write_text(json.dumps({'embedding_model':'test'}));client=FakeClient()
            with patch('tfgm_knowledge.ingest.Client.configured',return_value=client),patch('tfgm_knowledge.ingest.remote_content',side_effect=lambda *_:client.content):
                first,_=import_pack(str(p/'manifest.json'),config)
                again,_=import_pack(str(p/'manifest.json'),config)
                self.assertTrue(first['ready']);self.assertTrue(again['ready']);self.assertEqual(client.uploads,1)
                client.content=b'externally modified'
                with self.assertRaisesRegex(RuntimeError,'已被修改'):import_pack(str(p/'manifest.json'),config)
