"""Static command evidence for the explicit feature source set; never imports it."""
import ast
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from reference_inventory import inspect_file

VALID = re.compile(r'^[a-z][a-z0-9_]*$')


def candidates(path):
    """Return approximate names, not a claim that handlers are reachable."""
    text = path.read_text(errors='replace')
    names, flags = set(), []
    if path.suffix == '.py':
        _, found, flags = inspect_file(path)
        names.update(found)
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            return names, flags
        # CBML's explicit command dictionary; do not evaluate computed values.
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_static_commands' for t in node.targets):
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, TypeError, SyntaxError):
                    continue
                if isinstance(value, dict):
                    for item in value.values():
                        names.update([item] if isinstance(item, str) else [v for v in item if isinstance(v, str)] if isinstance(item, (list, tuple)) else [])
    elif path.suffix == '.ts' and 'commands' in path.parts and 'defineCommand' in text:
        names.update(re.findall(r'\bname\s*:\s*[\'"]([a-z][a-z0-9_]*)[\'"]', text))
        for aliases in re.findall(r'\baliases\s*:\s*\[([^\]]*)\]', text):
            names.update(re.findall(r'[\'"]([a-z][a-z0-9_]*)[\'"]', aliases))
    return {name for name in names if VALID.fullmatch(name)}, flags


def catalog(manifest, base):
    lines = ['# Explicit feature-source catalog', '',
             'Static source evidence only. No reference code, installers or startup scripts executed.',
             'The folders are ignored review checkouts, not runtime plugin imports.',
             'Command candidates may be unreachable, duplicated within one source or dynamically incomplete.', '',
             '| Feature | Checkout | Revision | Tracked files | Commands | License review |',
             '| --- | --- | --- | ---: | ---: | --- |']
    evidence, exceptions = defaultdict(list), []
    for source in manifest:
        root = base / source['path']
        revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
        if revision != source['revision']:
            raise ValueError('Reference revision mismatch: ' + source['path'])
        tracked = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z'], text=True).split('\0')
        all_names = set()
        for name in filter(None, tracked):
            path = root / name
            if path.suffix not in {'.py', '.ts'} or path.is_symlink() or not path.is_file():
                continue
            if path.stat().st_size > 2_000_000:
                exceptions.append(source['path'] + '/' + name + ': size limit')
                continue
            names, flags = candidates(path)
            exceptions.extend(source['path'] + '/' + name + ': ' + flag for flag in flags if flag.startswith('parse:'))
            all_names.update(names)
            for command in names:
                evidence[command].append((source['path'], name))
        lines.append(f"| {source['feature']} | [{source['path']}]({source['url']}) | `{revision}` | {len([n for n in tracked if n])} | {len(all_names)} | {source['license_review']} |")
    lines += ['', '## Candidate command ownership and collisions', '',
              'A collision means the same literal name appears in more than one requested checkout.',
              'It does not mean implementations are interchangeable. Resolve by shared core, explicit',
              'context or a reviewed namespace only when actually integrating the feature.', '',
              '| Command | Source checkouts | Evidence (maximum 4 files) |',
              '| --- | --- | --- |']
    for name, hits in sorted(evidence.items()):
        owners = sorted({owner for owner, _ in hits})
        lines.append(f"| `/{name}` | {', '.join(owners)} | " + ', '.join(f'`{owner}/{file}`' for owner, file in hits[:4]) + ' |')
    duplicates = sum(len({owner for owner, _ in hits}) > 1 for hits in evidence.values())
    lines += ['', f'Unique candidates: **{len(evidence)}**. Cross-checkout name collisions: **{duplicates}**.', '',
              '## Parse/size exceptions', '']
    lines.extend('- ' + item for item in exceptions)
    if not exceptions:
        lines.append('None found by this scanner.')
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    base = Path(__file__).resolve().parents[1]
    manifest = json.loads((base / 'docs/feature_sources.json').read_text())
    (base / sys.argv[1]).write_text(catalog(manifest, base))
