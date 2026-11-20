"""Evidence index, not an automatic command deletion tool. Never imports refs."""
import re
import sys
from pathlib import Path

from reference_inventory import inspect_file


def compare(root, commands):
    root = Path(root)
    literal, text_hits, failures = {}, {}, []
    source_files = []
    for repo in sorted(root.iterdir()):
        if not (repo / '.git').is_dir():
            continue
        for path in sorted(repo.rglob('*')):
            if not path.is_file() or path.is_symlink() or '.git' in path.relative_to(repo).parts:
                continue
            if path.suffix not in {'.py', '.js', '.ts', '.tsx', '.java', '.kt'}:
                continue
            if path.stat().st_size > 2_000_000:
                failures.append(str(path) + ': over size bound')
                continue
            relative = str(path.relative_to(root))
            text = path.read_text(errors='replace')
            source_files.append((relative, text))
            if path.suffix == '.py':
                _, candidates, flags = inspect_file(path)
                failures.extend(relative + ': ' + flag for flag in flags if flag.startswith('parse:'))
                for candidate in candidates:
                    if re.fullmatch('[a-z][a-z0-9_]*', candidate):
                        literal.setdefault(candidate, set()).add(relative)
    lines = ['# Agent command comparison across supplied references', '',
             'Read-only static evidence at the 29 revisions in `references/README.md`.',
             'No reference source was executed. Agent manifests are declarations, not live availability.',
             'Literal candidates come from command-like calls, not proven reachable handlers.',
             'Text hits include regex/dynamic/non-Python clues and can be unrelated identifiers.',
             '**Neither a name match nor absence establishes behavior parity or authorizes deletion.**', '',
             '| Agent command | Module | Evidence | Example source files (maximum 3) |',
             '| --- | --- | --- | --- |']
    counts = {'literal candidate': 0, 'source-text clue only': 0, 'no static match': 0}
    for name, module in sorted(commands):
        pattern = re.compile(r'(?<![A-Za-z0-9_])' + re.escape(name) + r'(?![A-Za-z0-9_])')
        hits = sorted(literal.get(name, ()))
        status = 'literal candidate'
        if not hits:
            hits = [path for path, text in source_files if pattern.search(text)]
            status = 'source-text clue only' if hits else 'no static match'
        text_hits[name] = hits
        counts[status] += 1
        evidence = ', '.join('`' + path + '`' for path in hits[:3]) or 'Manual review needed before removal'
        lines.append(f'| `/{name}` | {module} | {status} | {evidence} |')
    lines += ['', '## Coverage and limits', '', f'Commands compared: {len(commands)}. Source files searched: {len(source_files)}.',
              ', '.join(f'{key}: {value}' for key, value in counts.items()) + '.',
              'Parse/size exceptions: ' + str(len(failures)) + '.', '',
              'Exact aliases, regex registration, menus and argument-based subcommands need manual review.',
              'Non-source documentation and generated/binary assets are not command implementations.',
              'Do not add arbitrary shell/eval behavior just because a reference contains it.',
              'Existing branding, isolation, encryption and safety constraints remain in force.', '', '### Scan exceptions', '']
    lines += ['- ' + item for item in failures] or ['None.']
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    # Only Agent is imported to obtain expanded manifest aliases; refs stay inert.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from agent.modules import MODULES
    commands = {(name, module.MANIFEST.slug) for module in MODULES for name in module.MANIFEST.commands}
    commands.update((name, 'builtin') for name in ('start', 'help', 'ping'))
    Path(sys.argv[2]).write_text(compare(sys.argv[1], commands))
