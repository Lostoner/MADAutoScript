"""Inventory the release entry points' Python closure; never import the application.

Example: python snapshot_inventory.py --project . --output docs/architecture/new/inventory.json
Compare old and new module/qualified definition names, edge pairs, and SCCs.
"""
import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import runpy


def layer(name):
    if name == 'main': return 'bootstrap'
    if name == 'window' or name.startswith('gui.'): return 'ui'
    if name in ('core.Mad_thread', 'core.scheduler'): return 'execution'
    if name.startswith('core.config') or name in ('core.routine_checkpoint', 'core.runtime_state'): return 'storage'
    if name in ('core.game_catalog', 'core.tasks', 'core.routine_catalog'): return 'catalog_registry'
    if name=='module' or name.startswith('module.'): return 'game_tasks'
    if name=='core.device' or name.startswith('core.device.'): return 'device'
    if name.startswith('core.ocr.'): return 'ocr'
    if name in ('core.image', 'core.picture', 'core.position', 'core.color', 'core.mad_features'): return 'recognition'
    return 'common'


class Scan(ast.NodeVisitor):
    def __init__(self, name, package, known):
        self.name, self.package, self.known = name, package, known
        self.scope, self.defs, self.refs = [], [], []
        self.type_only = False

    def reference(self, target, node):
        # Record absent first-party type targets without inventing runtime nodes.
        if target in self.known or (self.type_only and target.split('.')[0] in ('core','gui','module')):
            self.refs.append((self.name,target,self.type_only,node.lineno,'.'.join(self.scope)))

    def visit_If(self, node):
        if ast.unparse(node.test) not in ('typing.TYPE_CHECKING','TYPE_CHECKING'):
            return self.generic_visit(node)
        previous, self.type_only = self.type_only, True
        for child in node.body: self.visit(child)
        self.type_only = previous
        for child in node.orelse: self.visit(child)

    def visit_Import(self, node):
        for alias in node.names: self.reference(alias.name,node)

    def visit_ImportFrom(self, node):
        base = node.module or ''
        if node.level:
            parts = self.package.split('.')
            base = '.'.join(parts[:len(parts)-node.level+1] + ([base] if base else []))
        for alias in node.names:
            child = base + '.' + alias.name
            self.reference(child if child in self.known else base,node)

    def definition(self,node):
        self.scope.append(node.name)
        self.defs.append({'name':'.'.join(self.scope),'kind':type(node).__name__,'line':node.lineno})
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = definition


def cycles(names,pairs):
    graph = {name:set() for name in names}
    for start,end in pairs: graph[start].add(end)
    def reach(start):
        todo, reached=[start],set()
        while todo:
            current=todo.pop()
            if current not in reached:
                reached.add(current)
                todo.extend(graph[current]-reached)
        return reached
    closure={name:reach(name) for name in names}
    groups={tuple(sorted(n for n in closure[name] if name in closure[n])) for name in names}
    return sorted(g for g in groups if len(g)>1 or g[0] in graph[g[0]])


def inventory(root):
    # Exactly the application's Python sources selected by the real release builder.
    files=runpy.run_path(str(root/'scripts/build_release.py'))['source_files']()
    modules={p.removesuffix('.py').replace('/','.').removesuffix('.__init__'):p for p in files}
    rows, references=[], set()
    for name,path in sorted(modules.items()):
        package=name if path.endswith('/__init__.py') else name.rpartition('.')[0]
        scan=Scan(name,package,modules)
        scan.visit(ast.parse((root/path).read_text(encoding='utf-8-sig')))
        rows.append({'module':name,'path':path,'layer':layer(name),'definitions':sorted(scan.defs,key=lambda d:d['name'])})
        references.update(scan.refs)
    pairs={(a,b) for a,b,t,_,_ in references if not t}
    by_layer=Counter((layer(a),layer(b)) for a,b in pairs)
    return {
        'format':1,
        'scope':"scripts/build_release.py:source_files() from main and window; includes package initializers",
        'edge_semantics':'First-party explicit Python imports. Function-local imports included; implicit parent-package loads, external imports and dynamic calls are excluded. TYPE_CHECKING references are recorded separately from runtime edges. SCCs imply mutual source dependencies, not necessarily initialization-time cycles.',
        'counts':{'modules':len(rows),'classes':sum(d['kind']=='ClassDef' for m in rows for d in m['definitions']),
                  'functions_and_methods_including_nested':sum(d['kind']!='ClassDef' for m in rows for d in m['definitions']),
                  'runtime_import_pairs':len(pairs),'cross_layer_runtime_import_pairs':sum(n for (a,b),n in by_layer.items() if a!=b)},
        'layer_module_counts':dict(sorted(Counter(m['layer'] for m in rows).items())),
        'layer_import_pairs':[{'from':a,'to':b,'module_pairs':n} for (a,b),n in sorted(by_layer.items())],
        'runtime_import_cycles':cycles(modules,pairs),
        'modules':rows,
        'imports':[{'from':a,'to':b,'type_checking_only':t,'line':line,'scope':scope or '<module>'}
                   for a,b,t,line,scope in sorted(references)]
    }


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[3])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    data=inventory(args.project.resolve())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(data['counts']))
