# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare/check/build modular drawing recipes. Run with --help for commands."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bonsai_sketch_mode'))


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'build', 'check'])
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args(argv)
    if args.input.resolve() == args.output.resolve() or args.output.exists():
        parser.error('Choose a new output path; input and existing outputs are preserved')
    try:
        if args.operation == 'check':
            import ifcopenshell
            from drawing_tools.checks import check
            findings = check(ifcopenshell.open(str(args.input)))
            write_json(args.output, findings)
            return int(any(f['severity'] == 'error' for f in findings))
        data = json.loads(args.input.read_text(encoding='utf-8-sig'))
        if args.operation == 'prepare':
            from drawing_tools.project import prepare
            recipe = prepare(data, args.input.parent)
            write_json(args.output, recipe)
            return int(any(f['severity'] == 'error' for f in recipe['findings']))
        from drawing_tools.ifc import build
        from drawing_tools.checks import check
        model = build(data)
        findings = check(model)
        if any(f['severity'] == 'error' for f in findings):
            print(json.dumps(findings, indent=2), file=sys.stderr)
            return 1
        model.write(str(args.output))
        print(json.dumps({'output': str(args.output), 'findings': findings}, indent=2))
        return 0
    except (ValueError, KeyError, OSError, TypeError) as exc:
        print(f'Drawing pipeline: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
