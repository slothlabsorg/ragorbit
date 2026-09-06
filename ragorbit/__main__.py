"""CLI de RAGorbit (stdlib).

    python -m ragorbit list-nodes [--json]
    python -m ragorbit validate <flow.json> [<flow.json> ...]
    python -m ragorbit generate <flow.json> --out <dir>
    python -m ragorbit serve [--port 8000] [--root .]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .registry import load_registry
from .validator import validate_flow


def _cmd_list_nodes(args) -> int:
    reg = load_registry()
    if args.json:
        print(json.dumps(reg.to_palette(), ensure_ascii=False, indent=2))
        return 0
    cats = reg.by_category()
    total = 0
    for cat in sorted(cats):
        print(f"\n=== {cat} ({len(cats[cat])}) ===")
        for m in cats[cat]:
            total += 1
            print(f"  {m.type:<26} {m.title}")
    print(f"\nTotal: {total} tipos de nodo en {len(cats)} categorías.")
    return 0


def _cmd_validate(args) -> int:
    reg = load_registry()
    rc = 0
    for path in args.flows:
        flow = json.loads(Path(path).read_text(encoding="utf-8"))
        res = validate_flow(flow, reg)
        name = flow.get("flow", {}).get("id", path)
        mark = "✅" if res.ok else "❌"
        print(f"{mark} {name}: {len(res.errors)} errores, {len(res.warnings)} warnings")
        for e in res.errors:
            print(f"     ERROR  {e}")
            rc = 1
        if args.verbose:
            for w in res.warnings:
                print(f"     warn   {w}")
    return rc


def _cmd_generate(args) -> int:
    from .codegen import generate_project

    flow = json.loads(Path(args.flow).read_text(encoding="utf-8"))
    reg = load_registry()
    res = validate_flow(flow, reg)
    if not res.ok:
        print(f"❌ Flow inválido, no se genera. Errores:")
        for e in res.errors:
            print(f"   - {e}")
        return 1
    out = Path(args.out)
    generate_project(flow, out, reg)
    print(f"✅ Proyecto generado en {out} (target={flow['flow']['deploymentTarget']})")
    return 0


def _cmd_serve(args) -> int:
    from .server import serve

    serve(port=args.port, root=Path(args.root))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ragorbit", description="RAGorbit engine CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list-nodes", help="Lista el catálogo de nodos")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=_cmd_list_nodes)

    pv = sub.add_parser("validate", help="Valida uno o más flow.json")
    pv.add_argument("flows", nargs="+")
    pv.add_argument("-v", "--verbose", action="store_true")
    pv.set_defaults(func=_cmd_validate)

    pg = sub.add_parser("generate", help="Genera un proyecto desde un flow.json")
    pg.add_argument("flow")
    pg.add_argument("--out", required=True)
    pg.set_defaults(func=_cmd_generate)

    ps = sub.add_parser("serve", help="Levanta el backend + UI (dev, stdlib)")
    ps.add_argument("--port", type=int, default=8000)
    ps.add_argument("--root", default=".")
    ps.set_defaults(func=_cmd_serve)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
