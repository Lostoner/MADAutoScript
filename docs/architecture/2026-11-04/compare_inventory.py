"""Compare two MAD architecture inventories. Line moves are not topology changes."""
import argparse
import json
from pathlib import Path


def structures(data):
    modules = data['modules']
    return {
        'modules': {m['module'] for m in modules},
        'module_layers': {(m['module'], m['layer']) for m in modules},
        'definitions': {(m['module'], d['kind'], d['name']) for m in modules for d in m['definitions']},
        'runtime_import_pairs': {(e['from'], e['to']) for e in data['imports'] if not e['type_checking_only']},
        'mutual_dependency_groups': {tuple(group) for group in data['runtime_import_cycles']},
    }


def compare(before, after):
    if before['format'] != after['format'] or before['scope'] != after['scope']:
        raise ValueError('Inventory format or scope changed; normalize both scans first.')
    old, new = structures(before), structures(after)
    return {key: {'added': sorted(values - old[key]), 'removed': sorted(old[key] - values)}
            for key, values in new.items() if values != old[key]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    args = parser.parse_args()
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    print(json.dumps(compare(read(args.before), read(args.after)), ensure_ascii=False, indent=2))
