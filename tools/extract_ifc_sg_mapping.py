"""Extract exact property bindings from the CORENET X mapping (needs openpyxl).

python tools/extract_ifc_sg_mapping.py asset/IFC-SG-Industry-Mapping-2025-12-04.xlsx
"""
import hashlib
import json
from pathlib import Path
import re
import sys

import openpyxl

SOURCE = 'https://info.corenet.gov.sg/ifc-sg/requirements---submission/ifc-sg-excel-mapping-file'
TYPES = {'Label': 'IfcLabel', 'Boolean': 'IfcBoolean', 'Length': 'IfcLengthMeasure',
         'Integer': 'IfcInteger', 'Real': 'IfcReal', 'Area': 'IfcAreaMeasure',
         'Volume': 'IfcVolumeMeasure', 'VolumetricFlowRate': 'IfcVolumetricFlowRateMeasure'}


def extract(path):
    sheet = openpyxl.load_workbook(path, read_only=True, data_only=True)['CX Pilot Mapping']
    rows = list(sheet.values)
    assert rows[0][11:14] == ('Property Set', 'Property Name', 'Property Type'), 'Unexpected workbook format'
    entries, excluded = [], []
    for number, row in enumerate(rows[1:], 2):
        cls, subtypes, pset, name, kind = (str(row[i] or '').strip() for i in (9, 10, 11, 12, 13))
        if not re.fullmatch(r'(?:SGPset_|SGPSet_|Pset_)\w+', pset):
            excluded.append({'row': number, 'reason': 'No explicit property binding'})
            continue
        if not re.fullmatch(r'Ifc\w+', cls) or kind not in TYPES or not name or '\ufffd' in name:
            excluded.append({'row': number, 'reason': 'Unknown type or damaged property name'})
            continue
        tokens = [s.strip() for s in subtypes.split(',')]
        if any(s != 'N.A' and not re.fullmatch(r'\*?[A-Z][A-Z0-9_]*', s) for s in tokens):
            excluded.append({'row': number, 'reason': 'Subtype requires external applicability review'})
            continue
        entries.append(dict(row=number, ifc_class=cls, subtypes=tokens, pset=pset,
                            name=name, measure=TYPES[kind], unit=str(row[14] or ''),
                            accepted_values=str(row[16] or ''), component=str(row[2] or ''),
                            agency=str(row[1] or '')))
    types = {}
    for entry in entries:
        types.setdefault((entry['pset'], entry['name']), set()).add(entry['measure'])
    valid = []
    for entry in entries:
        if len(types[entry['pset'], entry['name']]) != 1:
            excluded.append({'row': entry['row'], 'reason': 'Conflicting property types in source'})
        else:
            valid.append(entry)
    return dict(source=SOURCE, revision='2025-12-04',
                sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                scope='Published CX Pilot Mapping subset; no gateway applicability or default values inferred',
                entries=valid, excluded=sorted(excluded, key=lambda r: r['row']))


if __name__ == '__main__':
    data = extract(sys.argv[1])
    dest = Path(__file__).resolve().parents[1] / 'bonsai_sketch_mode/data/ifc_sg_mapping.json'
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f"Extracted {len(data['entries'])} bindings; {len(data['excluded'])} rows excluded: {dest}")
