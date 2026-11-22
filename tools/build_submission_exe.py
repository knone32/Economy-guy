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
    native=stage/'native';native.mkdir()
    for name in ('GuiWindow.exe','Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll','WebView2Loader.dll'):
        shutil.copy2(root/'finance_agent/app/webview_host'/name,native/name)
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--noconsole','--noupx',
        '--name','EconomyGuy','--distpath',str(stage/'dist'),'--workpath',str(stage/'work'),
        '--specpath',str(stage),'--paths',str(root/'finance_agent'),
        '--paths',str(root/'finance_agent/vendor/sqlglot-30.33.0-py3-none-any.whl')]
    for source,target in ((root/'finance_agent/gui','gui'),(config,'config'),
            (root/'finance_agent/tests/fixtures/example.xlsx','tests/fixtures'),
            (root/'finance_agent/vendor','vendor'),(native,'webview_host')):
        command+=['--add-data',str(source)+os.pathsep+target]
    command+=[str(root/'finance_agent/run_gui.py')]
    with (stage/'pyinstaller.log').open('w',encoding='utf-8') as log:
        subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT,check=True)
    shutil.copytree(stage/'dist/EconomyGuy',output)
    shutil.copytree(config,output/'config')
    (output/'功能说明.txt').write_text('工作台功能\n\n对话：业务查询、追问补充、修改要求、预览确认。\n待办：查看详情、进入办理、新建与更正任务、暂缓恢复和取消。\n业务查询：发票目录与详情、排序分页、月度年度汇总、银行收支、用途缺项、规则版本。\n资料：上传、更新版本、目录与精确原文。\n记录：切换历史对话，查看执行记录。\n设置：账户与账簿、Excel导入、已有账簿选择、模型配置、助手和阅读偏好。\n高级入口：连接诊断、结构诊断、固定脚本检查及原高级控制台。\n',encoding='utf-8-sig')
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
    (output/'使用说明.txt').write_text('Economy-guy 财税工作台\n\n1. 解压整个文件夹，双击 EconomyGuy.exe。\n2. 已备好演示账簿和账户配置，可直接查询发票、银行流水、用途缺项和规则。\n3. 对话、待办、业务查询、记录和设置均在窗口顶部；发票详情可带入对话继续办理。\n4. 修改内容先在预览中核对，再由本人确认保存；暂时不办理时可选择暂缓或取消。\n5. 模型配置在“设置”中管理；本机已有凭据可直接使用，需要时填写自己的API密钥。\n6. 账簿和会话保存在本文件夹的 data 目录，移动程序时请一并保留。\n\n运行环境：Windows 10/11 x64、.NET Framework 4.6.2+、Microsoft WebView2 Runtime。无需安装Python。\n',encoding='utf-8-sig')
    (output/'THIRD-PARTY-NOTICES.txt').write_text('''Native host: Microsoft WebView2 SDK libraries, reused from this workspace.
WebView2 Runtime: https://developer.microsoft.com/microsoft-edge/webview2/
Python runtime and third-party packages are embedded by PyInstaller from the build interpreter.
SQLGlot pinned wheel and its provenance are included inside the executable.
PyInstaller external-process startup follows its documented Windows DLL-search-path guidance:
https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html
''',encoding='utf-8')
    (output/'config/app-version.json').write_text(json.dumps({'name':'Economy-guy','source_sha':sha},ensure_ascii=False,indent=2),encoding='utf-8')
    manifest={'source_sha':sha,'source_root':str(root),'interpreter':sys.version,'public_profile':public,
        'preloaded_workbook':{'path':'data/demo.sqlite3','sha256':digest(book),'counts':counts,'invoice_audit':0},
        'files':{p.relative_to(output).as_posix():digest(p) for p in output.rglob('*') if p.is_file()},
        'gui':'native C# WebView2; no default-browser fallback','api_key_included':False,'old_sessions_included':False}
    (stage/'DELIVERY-VERSION.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=output.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in output.rglob('*'):
            if p.is_file():z.write(p,p.relative_to(output.parent))
    print(json.dumps({'folder':str(output),'archive':str(archive),'sha256':digest(archive),'source_sha':sha},ensure_ascii=False))


if __name__=='__main__':main()
