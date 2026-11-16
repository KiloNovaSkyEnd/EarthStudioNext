"""Owned-fixture fault injection; production cleanup contains no test switches."""
import importlib,importlib.util,os,pathlib,sys

if os.environ.get('EARTHSTUDIO_TEST_EXECUTION_CANDIDATE'):
    root=pathlib.Path(os.environ['EARTHSTUDIO_TEST_EXECUTION_CANDIDATE']).resolve()
    if not root.is_relative_to((pathlib.Path.cwd()/'reports').resolve()):raise ValueError('Test overlay outside reports')
    for name in ('ges_next.production.owned_files','ges_next.production.cleanup'):
        parent,leaf=name.rsplit('.',1);package=importlib.import_module(parent)
        spec=importlib.util.spec_from_file_location(name,root/pathlib.Path(*name.split('.')).with_suffix('.py'))
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);setattr(package,leaf,module)

import ges_next.production.cleanup as cleanup
if os.environ.get('CLEANUP_FIXTURE_CRASH_AFTER'):
    import ges_next.production.retention as retention
    original=retention.delete_verified;counter=[0]
    def crash(path,expected):
        original(path,expected);counter[0]+=1
        if counter[0]==int(os.environ['CLEANUP_FIXTURE_CRASH_AFTER']):raise RuntimeError('fixture crash after durable intent')
    retention.delete_verified=crash
cleanup.main()
