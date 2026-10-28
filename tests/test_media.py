import copy
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

from tfgm_knowledge.media import prepare_media, query_recipes, recipe_text, validate_media
from tfgm_knowledge.player_pack import build_pack, encoded, sha
from tfgm_knowledge.ingest import validate_pack
import test_player_pack


class MediaTests(unittest.TestCase):
    def fixture(self, root):
        bundle = root / 'bundle'
        record = test_player_pack.PlayerPackTests().fixture(bundle)
        record.update(id='guide',kind='field-guide',title='大桶',source_path='kubejs/assets/tfg/patchouli_books/field_guide/zh_cn/entries/barrels.json',data={'pages':[
            {'type':'patchouli:image','images':['tfc:textures/barrel.png'],'text':'桶界面'},
            {'type':'patchouli:multiblock','multiblock':{'pattern':[['0A']],'mapping':{'A':'tfc:barrel'}},'text':'结构'},
            {'type':'tfg:instant_barrel_recipe','recipe':'tfc:barrel/limewater','text':'石灰水'}]})
        (bundle/'records.jsonl').write_bytes(encoded(record).replace(b'\n',b'')+b'\n')
        recipe={'schema':1,'id':'tfc:barrel/limewater','category':'tfc:instant_barrel','widgets':[
            {'role':'input','x':0,'y':0,'interaction':{'kind':'fluid','id':'minecraft:water','amountMb':500}},
            {'role':'input','x':20,'y':0,'interaction':{'kind':'tag','tag':'tfc:flux','displayId':'tfc:powder/flux'}},
            {'role':'output','x':40,'y':0,'interaction':{'kind':'fluid','id':'tfc:limewater','amountMb':500}}]}
        payload={'build.json':encoded({'modpack':'0.13.17','releaseTag':'test'}),'assets/tfc/textures/barrel.png':b'\x89PNG\r\n\x1a\nfixture','emi/recipes/tfc/limewater.json':encoded(recipe),'emi/recipes/tfc/limewater.png':b'\x89PNG\r\n\x1a\nrecipe'}
        archive=root/'site.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            for name,data in payload.items():
                item=tarfile.TarInfo('./'+name);item.size=len(data);tar.addfile(item,io.BytesIO(data))
        source=root/'source.json';source.write_bytes(encoded({'game_version':'0.13.17','release_tag':'test','url':'https://example.org/site.tar.gz','sha256':sha(archive.read_bytes())}))
        return bundle,record,archive,source

    def test_pack_links_and_exact_recipe_lookup(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bundle,record,archive,source=self.fixture(root)
            folder,manifest=build_pack(bundle,root/'out','r2',media_site=archive,media_source=source)
            blob=(folder/Path(manifest['archive']['url']).name).read_bytes()
            contents=validate_pack(manifest,blob);index=validate_media(manifest,blob)
            self.assertIn('图片路径',contents['guide'].decode())
            self.assertEqual(len(index['structures']),1)
            recipes=query_recipes(index,item='tfc:limewater')
            self.assertEqual(recipes[0]['inputs'][0]['interaction']['amountMb'],500)
            self.assertIn('导出未注明数量',recipe_text(recipes[0]))
            self.assertEqual(query_recipes(index,item='tfc:powder/flux',direction='input'),[]) # displayId is not an exact ingredient requirement
            self.assertEqual(len(query_recipes(index,item='tfc:flux',direction='input')),1)
            self.assertNotIn('amount',recipes[0]['inputs'][1]['interaction'])
            _,again=build_pack(bundle,root/'out','r2',media_site=archive,media_source=source)
            self.assertEqual(manifest,again)

    def test_version_and_archive_integrity_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bundle,record,archive,source=self.fixture(root)
            data=json.loads(source.read_text());data['game_version']='0.13.15';source.write_bytes(encoded(data))
            with self.assertRaisesRegex(ValueError,'版本'):prepare_media(bundle,[record],archive,source)
            data['game_version']='0.13.17';data['sha256']='0'*64;source.write_bytes(encoded(data))
            with self.assertRaisesRegex(ValueError,'SHA256'):prepare_media(bundle,[record],archive,source)

    def test_tampered_asset_and_missing_relation_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bundle,record,archive,source=self.fixture(root)
            folder,manifest=build_pack(bundle,root/'out','r2',media_site=archive,media_source=source)
            blob=(folder/Path(manifest['archive']['url']).name).read_bytes()
            for mutation in ('image','relation'):
                out=io.BytesIO();m=copy.deepcopy(manifest)
                with zipfile.ZipFile(io.BytesIO(blob)) as original,zipfile.ZipFile(out,'w') as changed:
                    for name in original.namelist():
                        data=original.read(name)
                        if mutation=='image' and name.startswith('assets/'):data+=b'tampered'
                        if mutation=='relation' and name=='media.json':
                            index=json.loads(data);index['documents']['guide']['recipes']=['missing'];data=encoded(index);m['media'].update(sha256=sha(data),size=len(data))
                        changed.writestr(name,data)
                altered=out.getvalue();m['archive'].update(sha256=sha(altered),size=len(altered))
                with self.assertRaises(ValueError):validate_pack(m,altered)

    def test_tar_traversal_rejected_even_with_matching_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bundle,record,archive,source=self.fixture(root)
            with tarfile.open(archive,'w:gz') as tar:
                member=tarfile.TarInfo('../escape');member.size=1;tar.addfile(member,io.BytesIO(b'x'))
            data=json.loads(source.read_text());data['sha256']=sha(archive.read_bytes());source.write_bytes(encoded(data))
            with self.assertRaisesRegex(ValueError,'不安全'):prepare_media(bundle,[record],archive,source)

    def test_retrieval_returns_document_media_without_inventing_values(self):
        from unittest.mock import patch
        from tfgm_knowledge.evaluate import retrieve
        from tfgm_knowledge.media import cache_media
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bundle,record,archive,source=self.fixture(root)
            folder,manifest=build_pack(bundle,root/'out','r2',media_site=archive,media_source=source)
            blob=(folder/Path(manifest['archive']['url']).name).read_bytes()
            directory=cache_media(manifest,blob,root/'cache');index=validate_media(manifest,blob)
            report={'ready':True,'dataset_id':'dataset','media_directory':str(directory),'documents':{'guide':{'document_id':'remote','title':'大桶','source_url':record['source_url'],'media':index['documents']['guide']}}}
            class Client:
                def call(self,*args):return {'chunks':[{'document_id':'remote','content':'石灰水','similarity':.9}]},None
            with patch('tfgm_knowledge.evaluate.Client.configured',return_value=Client()):
                results=retrieve('unused',report,'石灰水怎么做')
            self.assertTrue(Path(results[0]['images'][0]['local_path']).is_file())
            self.assertEqual(len(results[0]['structures']),1)
            self.assertEqual(results[0]['recipes'][0]['id'],'tfc:barrel/limewater')
            self.assertNotIn('amount',results[0]['recipes'][0]['inputs'][1]['interaction'])

    def test_official_links_keep_snapshot_provenance(self):
        from tfgm_knowledge.media import image_reference, preview
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bundle,record,archive,source=self.fixture(root)
            _,index=prepare_media(bundle,[record],archive,source)
            index['source']['url']='https://github.com/TerraFirmaGreg-Team/Field-Guide-Modern/releases/download/test/site.tar.gz'
            image=index['documents']['guide']['images'][0]
            result=image_reference(image,index,root)
            self.assertEqual(result['url'],'https://wiki.terrafirmagreg.team/modern/field-guide/assets/tfc/textures/barrel.png')
            self.assertEqual(result['game_version'],'0.13.17')
            self.assertEqual(len(result['sha256']),64)
            self.assertIn(result['url'],preview(index,[record],remote_images=True))
            self.assertNotIn('https://wiki.terrafirmagreg.team',preview(index,[record]))
