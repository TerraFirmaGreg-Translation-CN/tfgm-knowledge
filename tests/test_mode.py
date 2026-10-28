import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('mode', Path(__file__).resolve().parents[1] / 'scripts/mode.py')
mode = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mode)

class ModeTests(unittest.TestCase):
    def test_colors(self):
        for env, tty, machine, expected in [({'TERM':'xterm'}, True, False, True), ({'NO_COLOR':'','FORCE_COLOR':'1'}, True, False, False), ({'FORCE_COLOR':'0'}, True, False, False), ({'FORCE_COLOR':'1'}, False, False, True), ({'FORCE_COLOR':'1'}, True, True, False), ({}, False, False, False)]:
            self.assertEqual(mode.color_enabled(env, tty, machine), expected)

    def test_watermarks_hysteresis(self):
        for used, old, expected in [(74,0,0),(75,0,1),(85,0,2),(92,0,3),(86,3,3),(84,3,1),(80,2,2),(77,2,1),(71,1,1),(69,1,0)]:
            self.assertEqual(mode.pressure(used, old), expected)

    def test_cleanup_boundaries_and_readonly(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(mode, 'LOCAL', Path(tmp)):
            cache = Path(tmp)/'cache'; cache.mkdir()
            p = cache/'old'; p.write_text('cache')
            other = Path(tmp)/'database'; other.write_text('persistent')
            alias = cache/'alias'; alias.symlink_to(other)
            base = {'repoKey':mode.KEY,'kind':'temporary','firstObserved':0}
            items = [{**base,'path':str(x)} for x in [p,alias,other]]
            self.assertEqual([x['path'] for x in mode.candidates(8*86400,items)], [str(p)])
            self.assertFalse(mode.candidates(8*86400,[{**items[0],'protected':True}]))
            self.assertFalse(mode.candidates(8*86400,[{**items[0],'repoKey':'other'}]))
            self.assertFalse(mode.candidates(8*86400,[{'path':str(p),'repoKey':mode.KEY,'kind':'temporary'}]))
            mode.write(Path(tmp)/'cache-manifest.json',items)
            before = {x.name:x.stat().st_mtime_ns for x in Path(tmp).iterdir()}
            mode.clean(None,True)
            self.assertEqual(before,{x.name:x.stat().st_mtime_ns for x in Path(tmp).iterdir()})
            mode.clean(None)
            self.assertFalse(p.exists())
            self.assertEqual(other.read_text(),'persistent')

    def test_config_corruption_and_identity(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(mode,'CONFIG',Path(tmp)/'mode.json'):
            mode.CONFIG.write_text('invalid')
            with self.assertRaises(ValueError): mode.config()
            mode.write(mode.CONFIG,{'version':2,'repoKey':mode.KEY})
            with self.assertRaises(ValueError): mode.config()

    def test_console_fixtures(self):
        s = mode.status(None)
        for state, text in [('stopped','已停止'),('unhealthy','健康异常')]:
            s['state']=state
            for columns in [40,80]:
                output=mode.render('status',s,False,columns)
                self.assertIn(text,output)
                self.assertNotIn('\033',output)
                self.assertNotIn('https://127.0.0.1:',output)
        self.assertIn('\033[1m',mode.render('help',color=True))
        self.assertEqual(mode.width('中文ab'),6)
        for group in mode.COMMANDS.values():
            for cmd in group:self.assertIn('mode:'+cmd,mode.render('help'))

    def test_lock_excludes_concurrency(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(mode,'LOCAL',Path(tmp)):
            with mode.lock():
                with self.assertRaises(RuntimeError):
                    with mode.lock():pass

    def test_admin_failure_never_marks_initialized(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp, patch.object(mode,'LOCAL',Path(tmp)), patch.object(mode,'GENERATED',Path(tmp)):
            mode.write(Path(tmp)/'credentials.json',{'admin':'secret-value'})
            fake_container={'Id':'owned-id','Config':{'Labels':{'dev.tfgm.service':'ragflow'}}}
            def fake_process(argv, **kwargs):
                self.assertNotIn('secret-value',' '.join(argv))
                if argv[0]=='openssl': return SimpleNamespace(stdout=b'cipher')
                return SimpleNamespace(returncode=0,stdout='HTTP/1.1 200 OK\n\n{"code":109}')
            with patch.object(mode,'containers',return_value=[fake_container]), patch.object(mode,'run',return_value=SimpleNamespace(stdout='public-key')), patch.object(mode.subprocess,'run',side_effect=fake_process):
                with self.assertRaisesRegex(RuntimeError,'管理员初始化失败'):mode.bootstrap_admin()
            self.assertFalse((Path(tmp)/'admin-initialized.json').exists())

    def test_workspace_account_migration_checks_authorization(self):
        import json
        from types import SimpleNamespace
        for workspace_code in [0, 403]:
            with self.subTest(workspace_code=workspace_code), tempfile.TemporaryDirectory() as tmp, patch.object(mode,'LOCAL',Path(tmp)), patch.object(mode,'GENERATED',Path(tmp)):
                mode.write(Path(tmp)/'credentials.json',{'admin':'admin-secret'})
                marker=Path(tmp)/'admin-initialized.json'
                mode.write(marker,{'repoKey':mode.KEY})
                codes=iter([0,109,0,0,workspace_code,0,0,0])
                requests=[]
                def fake_process(argv, **kwargs):
                    if argv[0]=='openssl':return SimpleNamespace(stdout=b'encrypted')
                    requests.append(kwargs['input'])
                    code=next(codes)
                    return SimpleNamespace(returncode=0,stdout='HTTP/1.1 200 OK\nAuthorization: test-token\n\n'+json.dumps({'code':code,'data':{'chats':[]}}))
                with patch.object(mode,'containers',return_value=[{'Id':'owned','Config':{'Labels':{'dev.tfgm.service':'ragflow'}}}]), patch.object(mode,'run',return_value=SimpleNamespace(stdout='public')), patch.object(mode.subprocess,'run',side_effect=fake_process):
                    if workspace_code:
                        with self.assertRaisesRegex(RuntimeError,'无权读取'):mode.bootstrap_admin()
                        self.assertNotEqual(mode.read(marker).get('version'),2)
                    else:
                        mode.bootstrap_admin()
                        self.assertEqual(mode.read(marker)['version'],2)
                        self.assertEqual(len(requests),8)
                payload=json.loads(next(line.split(' = ',1)[1] for line in requests[2].splitlines() if line.startswith('data = ')))
                self.assertEqual(json.loads(payload)['role'],'user')
                credentials=mode.read(Path(tmp)/'credentials.json')
                self.assertEqual(credentials['admin'],'admin-secret')
                self.assertIn('user',credentials)
