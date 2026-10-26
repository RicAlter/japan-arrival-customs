"""Maintenance-only facade for the shared product-reference SQLite.

The implementation is loaded from the sibling arrival Skill in the same
release bundle.  The two Skills therefore share one schema while ownership is
separated: this facade writes; the arrival facade only reads.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path


def core():
    sibling = Path(__file__).resolve().parents[2] / "japan-arrival-customs" / "scripts"
    if not sibling.is_dir():
        raise SystemExit("缺少同发布包的日本到货主Skill运行时，不能安全维护共享资料库")
    sys.path.insert(0, str(sibling))
    from arrival_core.product_library import ProductLibrary
    from arrival_core.core import Rejected
    return ProductLibrary, Rejected


def main(argv=None):
    parser = argparse.ArgumentParser(description="日本到货共享商品资料库维护；不处理D1/D2/D3")
    parser.add_argument("--library", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import"); imp.add_argument("--sources", nargs="+", required=True)
    imp.add_argument("--source-kind", default="auto", choices=["auto", "purchase_order", "product_archive", "historical_arrival", "official_reference", "historical_material"])
    lookup = sub.add_parser("lookup"); lookup.add_argument("--code", required=True); lookup.add_argument("--japanese-name", default=""); lookup.add_argument("--version", default="")
    queue = sub.add_parser("apply-queue"); queue.add_argument("--file", required=True)
    sub.add_parser("init"); sub.add_parser("stats")
    args = parser.parse_args(argv); ProductLibrary, Rejected = core()
    try:
        if args.command == "init": value = {"created": True, "statistics": ProductLibrary.create(args.library).statistics()}
        else:
            library = ProductLibrary(args.library)
            if args.command == "import": value = library.import_workbooks(args.sources, source_kind=args.source_kind)
            elif args.command == "stats": value = library.statistics()
            elif args.command == "lookup": value = library.lookup(args.code, japanese_name=args.japanese_name, version=args.version)
            else:
                queue_data = json.loads(Path(args.file).read_text(encoding="utf-8"))
                bound = queue_data.get("library", {})
                path = Path(args.library).resolve()
                if bound.get("path") != str(path) or bound.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
                    raise Rejected("维护队列与当前SQLite快照不一致；请重新从主Skill生成确认队列")
                value = library.record_maintenance_records(queue_data.get("records"), queue_data.get("confirmation"))
        print(json.dumps(value, ensure_ascii=False)); return 0
    except Rejected as exc:
        print(json.dumps({"error": str(exc), "formal_output": False}, ensure_ascii=False)); return 2


if __name__ == "__main__":
    raise SystemExit(main())
