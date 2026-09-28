"""Exercise the real wrapper with in-memory files; no user code reaches hardware."""
import io, json
from pathlib import Path
source=(Path(__file__).resolve().parents[1]/'sdcard/labplus/generated_runner.py').read_text()
def check(code, expected):
    files={'/sdcard/labplus/program-selection.json':json.dumps({'id':'test','path':'/sdcard/programs/demo.py'}),'/sdcard/programs/demo.py':code}
    class Writer(io.StringIO):
        def __init__(self,path): super().__init__();self.path=path
        def close(self):
            if not self.closed: files[self.path]=self.getvalue()
            super().close()
    def fake_open(path,mode='r'):
        return Writer(path) if mode=='w' else io.StringIO(files[path])
    exec(compile(source,'generated_runner.py','exec'),{'open':fake_open})
    result=json.loads(files['/sdcard/labplus/program-status.json'])
    assert result['state']==expected,result
    return result
assert check('print("hello", 123)','done')['output']=='hello 123\n'
assert check('raise ValueError("test error")','failed')['error']=='test error'
assert check('this is invalid syntax!','failed')['state']=='failed'
assert check('print("x"*5000)','done')['overflow'] is True
print('PASS: real Python wrapper stdout capture, runtime error, syntax error')
