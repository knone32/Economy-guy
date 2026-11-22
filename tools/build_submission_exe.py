"""Build a clean native-window submission using only this checkout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import zipfile


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();output=args.output.resolve()
    git=['git','-c','safe.directory='+root.as_posix(),'-C',str(root)]
    sha=subprocess.check_output(git+['rev-parse','HEAD'],text=True).strip()
    if subprocess.check_output(git+['status','--porcelain'],text=True).strip():raise ValueError('Commit source first')
    if output.exists() or output.with_suffix('.zip').exists():raise FileExistsError(output)
    stage=root/'artifacts/native-host-20261122'/('build-'+sha[:7]);stage.mkdir(parents=True,exist_ok=False)
    config=stage/'public-config';config.mkdir()
    local=json.loads((root/'finance_agent/config/model_profiles.local.json').read_text(encoding='utf-8-sig'))
    profile=next(p for p in local['profiles'] if p['profile_name']=='shared-flash')
    public={k:profile[k] for k in ('profile_name','scope','owner_user_id','provider','service_account_ref',
        'model','base_url','api_key_env','protocol') if profile.get(k) is not None}
    text='[settings]\ndefault_profile = "shared-flash"\n\n[[profiles]]\n'
    text+=''.join(k+' = '+json.dumps(v,ensure_ascii=False)+'\n' for k,v in public.items())
    (config/'model_profiles.toml').write_text(text,encoding='utf-8')
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--noconsole','--noupx',
        '--name','EconomyGuy','--distpath',str(stage/'dist'),'--workpath',str(stage/'work'),
        '--specpath',str(stage),'--paths',str(root/'finance_agent'),
        '--paths',str(root/'finance_agent/vendor/sqlglot-30.33.0-py3-none-any.whl')]
    for source,target in ((root/'finance_agent/gui','gui'),(config,'config'),
            (root/'finance_agent/tests/fixtures/example.xlsx','tests/fixtures'),
            (root/'finance_agent/vendor','vendor'),(root/'finance_agent/app/webview_host','webview_host')):
        command+=['--add-data',str(source)+os.pathsep+target]
    command+=[str(root/'finance_agent/run_gui.py')]
    with (stage/'pyinstaller.log').open('w',encoding='utf-8') as log:
        subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT,check=True)
    output.mkdir(parents=True);shutil.copy2(stage/'dist/EconomyGuy.exe',output/'EconomyGuy.exe')
    shutil.copytree(config,output/'config')
    sys.path.insert(0,str(root/'finance_agent'))
    from app.gui_delivery import demo_paths
    book,_=demo_paths(output/'data')
    from app.assistant_config import configure
    from app.agent import Agent
    from app.tool_registry import REGISTRY
    original=Agent('U001',book,model=lambda *a:None,mode='mock')
    configure(book,'U001','assistant','finance-default',{'name':'财税业务助手',
        'tools':sorted(set(REGISTRY)&set(original.allowed_tools)),'skills':[]},capabilities=('assistant.manage',))
    with sqlite3.connect(book) as db:
        accounts=[{'user_id':row[0],'display_name':row[1]} for row in db.execute('SELECT * FROM users')]
        permissions=[{'user_id':u,'company_id':c,'can_read':bool(r),'can_modify':bool(m)}
                     for u,c,r,m in db.execute('SELECT user_id,company_id,can_read,can_modify FROM permissions')]
        assert db.execute('SELECT count(*) FROM invoice_audit').fetchone()[0]==0
        counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('invoices','bank_transactions','rules')}
    account={'version':1,'identity_mode':'local_trusted_simulation','active_user_id':'U001',
             'model_profile':'shared-flash','accounts':accounts,'permissions_reference_only':permissions,
             'authority':'Actual permissions are checked against the workbook; this is not production login.'}
    (output/'config/accounts.json').write_text(json.dumps(account,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'使用说明.txt').write_text('''双击 EconomyGuy.exe，等待内嵌工作台出现；不会打开默认浏览器。
已预制官方虚构账簿 data/demo.sqlite3，初始修改审计为零。程序只使用本包旁的数据和会话库。
U001可读改C001/C002；U002仅可读C001。默认U001，属于本机受信模拟绑定，不是生产登录认证。
config/accounts.json选择启动模拟用户；实际权限每次由账簿核验，不由配置声明授予。
config/model_profiles.toml含既定DeepSeek Flash的公开Profile身份；没有实际API密钥。
同一Windows用户可复用已有Windows凭据库；新机器需配置自己的DEEPSEEK_API_KEY或原凭据。
缺少密钥仍可打开设置、浏览账簿；可在设置里新增Profile并将密钥保存在Windows凭据库。
GUI含发票分页/详情、银行流水/方向、综合汇总、用途缺项、规则版本、资料、会话记录、助手/偏好、模拟绑定切换与xlsx导入。
需要Windows 10/11 x64、.NET Framework 4.6.2+和WebView2 Runtime。本机已验证已有运行时。
预览不是保存，必须本人确认当前预览。未知提交只能先核查，不能盲目重复提交。
关闭窗口会正常停止本机服务。异常请看 logs/startup.log及window状态文件。
包内没有旧会话、旧批准、用户历史或本机密钥。程序首次启动才创建新的会话库。
已知业务限制：等待选择已直接绑定，但仅报错月票号后的执行动作仍有未闭环失败；不声明全业务通过。
''',encoding='utf-8-sig')
    (output/'THIRD-PARTY-NOTICES.txt').write_text('''Native host: Microsoft WebView2 SDK libraries, reused from this workspace.
WebView2 Runtime: https://developer.microsoft.com/microsoft-edge/webview2/
Python runtime and third-party packages are embedded by PyInstaller from the build interpreter.
SQLGlot pinned wheel and its provenance are included inside the executable.
PyInstaller external-process startup follows its documented Windows DLL-search-path guidance:
https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html
''',encoding='utf-8')
    manifest={'source_sha':sha,'source_root':str(root),'interpreter':sys.version,'public_profile':public,
        'preloaded_workbook':{'path':'data/demo.sqlite3','sha256':digest(book),'counts':counts,'invoice_audit':0},
        'files':{p.relative_to(output).as_posix():digest(p) for p in output.rglob('*') if p.is_file()},
        'gui':'native C# WebView2; no default-browser fallback','api_key_included':False,'old_sessions_included':False}
    (output/'DELIVERY-VERSION.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=output.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in output.rglob('*'):
            if p.is_file():z.write(p,p.relative_to(output.parent))
    print(json.dumps({'folder':str(output),'archive':str(archive),'sha256':digest(archive),'source_sha':sha},ensure_ascii=False))


if __name__=='__main__':main()
