"""Build an offline Windows GUI folder from explicit source/runtime allowlists.

No ledger, local profile file, database, trace, venv or credential is copied.
The selected public profile identity can reuse Windows Vault on the same user.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def build(source, output, profile_file, profile_name, runtime_archive):
    source=source.resolve();output=output.resolve()
    git=['git','-c','safe.directory='+source.as_posix(),'-C',str(source)]
    revision=subprocess.check_output(git+['rev-parse','HEAD'],text=True).strip()
    if subprocess.check_output(git+['status','--porcelain'],text=True).strip():
        raise ValueError('Freeze and commit the source first')
    if output.exists() or output.with_suffix('.zip').exists():raise FileExistsError(output)
    expected_runtime='4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'
    if sha(runtime_archive)!=expected_runtime:raise ValueError('Official Python 3.12.10 embed archive hash mismatch')
    profiles=json.loads(profile_file.read_text(encoding='utf-8-sig'))['profiles']
    choices=[p for p in profiles if p.get('profile_name')==profile_name]
    if len(choices)!=1:raise ValueError('Select one existing profile identity')
    fields=('profile_name','scope','owner_user_id','provider','service_account_ref',
            'model','base_url','api_key_env','protocol')
    public={key:choices[0][key] for key in fields if choices[0].get(key) is not None}
    output.mkdir(parents=True)
    selected=[]
    files=subprocess.check_output(git+['ls-files','-z']).decode('utf-8').split('\0')
    entries={'START-GUI.bat','finance_agent/run_gui.py','finance_agent/main.py',
             'finance_agent/requirements.txt','finance_agent/tests/fixtures/example.xlsx',
             'finance_agent/vendor/sqlglot-30.33.0-py3-none-any.whl',
             'finance_agent/vendor/README.md','finance_agent/vendor/SQLGLOT-PROVENANCE.txt'}
    for name in files:
        if name in entries or name.startswith(('finance_agent/app/','finance_agent/gui/')):
            path=Path(name)
            if path.suffix in {'.py','.html','.css','.js','.svg','.png','.ico','.xlsx','.bat','.txt','.md','.whl'}:
                target=output/path;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source/path,target);selected.append(name)
    config=output/'finance_agent/config';config.mkdir(parents=True)
    template='[settings]\ndefault_profile = '+json.dumps(profile_name)+'\n\n[[profiles]]\n'
    template+=''.join(key+' = '+json.dumps(value,ensure_ascii=False)+'\n' for key,value in public.items())
    (config/'model_profiles.toml').write_text(template,encoding='utf-8')
    runtime=output/'_runtime';runtime.mkdir()
    with zipfile.ZipFile(runtime_archive) as embed:
        if any(Path(i.filename).is_absolute() or '..' in Path(i.filename).parts for i in embed.infolist()):
            raise ValueError('Invalid runtime archive member')
        embed.extractall(runtime)
    site=Path(sys.prefix)/'Lib/site-packages'
    if sys.prefix==sys.base_prefix or not site.is_dir():raise ValueError('Run with the prepared 3.12 venv')
    shutil.copytree(site,runtime/'Lib/site-packages',ignore=shutil.ignore_patterns(
        '__pycache__','*.pyc','*.pyo','pip','pip-*.dist-info'))
    (runtime/'python312._pth').write_text('python312.zip\n.\nLib/site-packages\n../finance_agent\nimport site\n',encoding='ascii')
    launcher=r'''@echo off
setlocal DisableDelayedExpansion
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
call "%~dp0START-GUI.bat" --port 8770 --profile "PROFILE" --profiles-file "%~dp0finance_agent\config\model_profiles.toml" --profiles-local "%~dp0local-config\model_profiles.local.json" %*
'''.replace('PROFILE',profile_name)
    (output/'启动工作台.cmd').write_bytes(launcher.replace('\n','\r\n').encode('utf-8'))
    (output/'使用说明.txt').write_text('''双击“启动工作台.cmd”。首次无需安装Python或依赖，不使用系统Python。
此包为Windows x64本机演示版，使用官方虚构演示账簿。
首次启动才创建finance_agent/data/gui-demo；此包不包含旧账簿、会话、批准或历史卡片。
本清洁包默认http://127.0.0.1:8770/，与旧工作台8765分开。端口被占用时先关闭此包的旧窗口，或加 --port 8771。
启动窗口保持运行；Ctrl+C关闭。预览不是保存，只有本人确认后才提交。
包内只含公开Profile身份，不含密钥；同一Windows用户复用原Windows凭据库。
另一台机器或用户需要先配置自己的凭据；缺凭据会保留真实错误，不能自动借用其他账号。
原工作区数据完全保留。请不要删除需要保留的原账簿。
当前业务已知限制及真实验收版本见DELIVERY-VERSION.json；本包启动正常不代表所有业务链通过。
''',encoding='utf-8-sig')
    manifest={'source_sha':revision,'python':'3.12.10','runtime_archive_sha256':expected_runtime,'platform':'Windows x64',
              'public_profile':public,'source_files':selected,
              'known_business_limit':'A_SUBSET待选直达已通过Live，后续仅报错月票号的执行动作仍有未闭环失败；未宣称整链通过。',
              'excludes':['credentials','databases','session history','approval','traces','venv','development artifacts'],
              'files':{p.relative_to(output).as_posix():sha(p) for p in output.rglob('*') if p.is_file()}}
    (output/'DELIVERY-VERSION.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    for p in output.rglob('*'):
        public_ca=p.relative_to(output).as_posix()=='_runtime/Lib/site-packages/certifi/cacert.pem'
        if p.is_file() and (p.suffix.lower() in {'.db','.sqlite','.sqlite3','.jsonl','.log','.key'}
                           or p.suffix.lower()=='.pem' and not public_ca
                           or p.name in {'.env','model_profiles.local.json','pyvenv.cfg'}):
            raise ValueError('Unexpected private/state file: '+str(p.relative_to(output)))
    archive=output.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in output.rglob('*'):
            if p.is_file():z.write(p,p.relative_to(output.parent))
    print(json.dumps({'folder':str(output),'archive':str(archive),'source_sha':revision,
                      'sha256':sha(archive),'bytes':archive.stat().st_size},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--profile-source',type=Path,required=True)
    parser.add_argument('--runtime-archive',type=Path,required=True)
    parser.add_argument('--profile',default='shared-flash')
    args=parser.parse_args()
    build(Path(__file__).resolve().parents[1],args.output,args.profile_source,args.profile,args.runtime_archive)
