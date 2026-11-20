"""Explicit local material management; no model or invoice writes."""
import argparse
import json
from .materials import import_docx, list_materials, get_paragraph
from .stage2_schema import open_existing


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
    args = parser.parse_args(argv)
    if args.action == "upload":
        result = import_docx(args.db, args.user, args.company, args.file, args.name, args.material_id)
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
