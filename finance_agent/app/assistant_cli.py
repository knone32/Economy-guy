"""Local trusted configuration entry; no model requests."""
import argparse
import json
from contextlib import closing
from .assistant_config import configure, connect


def main():
    p=argparse.ArgumentParser(description='助手与共享能力配置（可信本地模拟管理入口）')
    p.add_argument('--db',required=True)
    p.add_argument('--actor',required=True)
    p.add_argument('--simulate-manager',action='store_true')
    p.add_argument('--kind',choices=['assistant','skill','tool'])
    p.add_argument('--id')
    p.add_argument('--body-file')
    p.add_argument('--revision',type=int,default=0)
    p.add_argument('--disable',action='store_true')
    a=p.parse_args()
    if a.body_file:
        with open(a.body_file,encoding='utf-8-sig') as f: body=json.load(f)
        result=configure(a.db,a.actor,a.kind,a.id,body,enabled=not a.disable,expected_revision=a.revision,
                         capabilities={'assistant.manage'} if a.simulate_manager else ())
    else:
        with closing(connect(a.db)) as db:
            result=[dict(r) for r in db.execute('SELECT kind,id,revision,enabled,body FROM assistant_config WHERE owner=?',(a.actor,))]
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
