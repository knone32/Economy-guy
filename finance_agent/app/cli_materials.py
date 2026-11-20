"""Explicit local material management; no model or invoice writes."""
import argparse
import json
from .materials import import_material, list_materials, get_paragraph
from .stage2_schema import open_existing


def _load_rule(filename):
    from .rules import make_rule
    with open(filename, encoding="utf-8-sig") as source:
        data = json.load(source)
    required = {"rule_id", "version", "name", "company_scope", "effective_from", "rule_type", "params"}
    if type(data) is not dict or not required <= data.keys() or data.keys() - required - {"status", "content"}:
        raise ValueError("规则JSON字段必须包含rule_id/version/name/company_scope/effective_from/rule_type/params")
    rule = make_rule(data["rule_id"], data["version"], data["name"], data["company_scope"],
                     data["effective_from"], data.get("status", "ACTIVE"), data["rule_type"], data["params"])
    if "content" in data and data["content"] != rule["content"]:
        raise ValueError("规则正文与执行参数不一致")
    return rule


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--user", required=True, help="trusted local simulation identity")
    sub = parser.add_subparsers(dest="action", required=True)
    upload = sub.add_parser("upload")
    upload.add_argument("--company", required=True)
    upload.add_argument("--file", required=True)
    upload.add_argument("--name")
    upload.add_argument("--material-id")
    listing = sub.add_parser("list")
    listing.add_argument("--company", required=True)
    opening = sub.add_parser("open")
    opening.add_argument("--material-id", required=True)
    opening.add_argument("--version", type=int, required=True)
    opening.add_argument("--paragraph-id", type=int, required=True)
    publish = sub.add_parser("publish-rule", help="显式管理发布规则并绑定已上传的版本原段；上传不会自动发布")
    publish.add_argument("--rule-file", required=True, help="UTF-8 JSON规则文件；执行正文由有限规则参数生成")
    publish.add_argument("--material-id", required=True)
    publish.add_argument("--version", type=int, required=True, help="资料版本号，不是JSON中的规则版本")
    publish.add_argument("--paragraph-id", type=int, required=True)
    publish.add_argument("--supersedes", nargs=2, metavar=("RULE_ID", "RULE_VERSION"),
                         help="显式截止的旧发布规则，截止日取新规则生效日")
    publish.add_argument("--simulate-manager", action="store_true",
                         help="可信本地模拟管理身份，授予独立rule.manage；不是生产认证")
    args = parser.parse_args(argv)
    if args.action == "upload":
        result = import_material(args.db, args.user, args.company, args.file, args.name, args.material_id)
    elif args.action == "publish-rule":
        from .rules import publish_material_rule
        if not args.simulate_manager:
            parser.error("缺少独立 rule.manage 权限；可信本地模拟管理员需显式 --simulate-manager")
        try:
            rule = _load_rule(args.rule_file)
            source_ref = {"material_id": args.material_id, "version": args.version, "paragraph_id": args.paragraph_id}
            result = publish_material_rule(args.db, rule, source_ref, {"rule.manage"}, actor=args.user,
                                           supersedes=tuple(args.supersedes) if args.supersedes else None)
        except (PermissionError, ValueError, TypeError, OSError) as error:
            parser.error(str(error))
        result = {**result, "rule_id": rule["rule_id"], "rule_version": rule["version"], "source": source_ref}
    else:
        connection = open_existing(args.db, readonly=True)
        try:
            result = (list_materials(connection, args.user, args.company) if args.action == "list" else
                      get_paragraph(connection, args.user, args.material_id, args.version, args.paragraph_id))
        finally:
            connection.close()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
