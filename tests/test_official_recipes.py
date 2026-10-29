import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tfgm_knowledge.official_recipes import OfficialRecipes, SITE, sync, openapi
from tfgm_knowledge.player_pack import encoded


class OfficialRecipeTests(unittest.TestCase):
    def fixture(self, root):
        build={'modpack':'0.13.15','contentHash':'abcd','releaseTag':'site-tfg-0.13.15-abcd'}
        data={
            'build.json':build, 'bundles.json':{'bundles':['tfg-0.13.15']},
            'bundles/tfg-0.13.15/bundle.json':{'schema':2,'recipeCount':2,'recipeImageFormat':'png'},
            'bundles/tfg-0.13.15/items/index.json':{'schema':1,'tfc':['limewater','bucket/limewater']},
            'bundles/tfg-0.13.15/items-lang/zh_cn.json':{'schema':2,'items':[{'id':'tfc:limewater','label':'石灰水','haystack':'tfc:limewater 石灰水 limewater'},{'id':'tfc:bucket/limewater','label':'石灰水桶','haystack':'tfc:bucket/limewater 石灰水桶'}]},
            'bundles/tfg-0.13.15/items/tfc/limewater.json':{'schema':2,'inputs':{'test:use':['test:uses']},'outputs':{'tfc:instant_barrel':['tmrv:/tfc/barrel/limewater']}},
            'bundles/tfg-0.13.15/recipes/tmrv/_tfc_barrel_limewater.json':{'schema':1,'id':'tmrv:/tfc/barrel/limewater','category':'tfc:instant_barrel','widgets':[{'role':'input','interaction':{'kind':'item','id':'tfc:powder/flux'}},{'role':'output','interaction':{'kind':'fluid','id':'tfc:limewater','amountMb':500}}]}}
        def fetch(url,limit):return encoded(data[url.removeprefix(SITE)])
        with patch('tfgm_knowledge.official_recipes.fetch',side_effect=fetch):path,manifest=sync('0.13.15',root)
        return path,data,fetch

    def test_search_reverse_index_recipe_and_offline_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            path,data,fetch=self.fixture(temp);client=OfficialRecipes(path,'0.13.15')
            self.assertEqual(client.search('石灰水')['items'][0]['id'],'tfc:limewater')
            with patch('tfgm_knowledge.official_recipes.fetch',side_effect=fetch):
                self.assertEqual(client.find('tfc:limewater')['total'],1)
                self.assertEqual(client.find('tfc:limewater','input')['recipes'][0]['id'],'test:uses')
                recipe=client.recipe('tmrv:/tfc/barrel/limewater')
            self.assertNotIn('amount',recipe['inputs'][0]['interaction'])
            self.assertFalse(recipe['route_calculation_supported'])
            self.assertTrue(recipe['image_url'].endswith('/recipes/tmrv/_tfc_barrel_limewater.png'))
            offline=OfficialRecipes(path,'0.13.15',offline=True)
            with patch('tfgm_knowledge.official_recipes.fetch',side_effect=AssertionError('offline network')):
                self.assertEqual(offline.recipe(recipe['id']),recipe)
                with self.assertRaisesRegex(ValueError,'离线缓存'):offline.find('tfc:missing')

    def test_versions_and_deployment_change_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path,data,fetch=self.fixture(temp)
            with self.assertRaisesRegex(ValueError,'版本'):OfficialRecipes(path,'0.13.17')
            with patch('tfgm_knowledge.official_recipes.fetch',side_effect=fetch):
                with self.assertRaisesRegex(ValueError,'拒绝'):sync('0.13.17',temp)
            client=OfficialRecipes(path,'0.13.15');data['build.json']['contentHash']='ffff'
            with patch('tfgm_knowledge.official_recipes.fetch',side_effect=fetch):
                with self.assertRaisesRegex(ValueError,'构建已变化'):client.find('tfc:limewater')

    def test_corruption_traversal_pagination_and_id_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            path,data,fetch=self.fixture(temp);client=OfficialRecipes(path,'0.13.15')
            for item in ['tfc:../../secret','tfc:/etc/passwd','https://example.com']:
                with self.assertRaises(ValueError):client.find(item)
            with self.assertRaises(ValueError):client.find('tfc:limewater',offset=-1)
            with self.assertRaises(ValueError):client.search('水',limit=101)
            data['bundles/tfg-0.13.15/recipes/tmrv/_tfc_barrel_limewater.json']['id']='other:id'
            with patch('tfgm_knowledge.official_recipes.fetch',side_effect=fetch):
                with self.assertRaisesRegex(ValueError,'ID'):client.recipe('tmrv:/tfc/barrel/limewater')
            for file in (path.parent/'cache').glob('*.json'):
                envelope=json.loads(file.read_text())
                if envelope['url'].endswith('items-lang/zh_cn.json'):
                    envelope['data']['items'][0]['label']='tampered';file.write_bytes(encoded(envelope))
            with self.assertRaisesRegex(ValueError,'校验失败'):client.search('水')

    def test_openapi_requires_version_on_all_operations(self):
        spec=openapi()
        for route in spec['paths'].values():
            self.assertTrue(next(p for p in route['get']['parameters'] if p['name']=='version')['required'])
