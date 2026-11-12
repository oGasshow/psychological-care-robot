"""Check repository Markdown links and navigation without network or services.

Checks public Git files (including untracked, non-ignored changes), skips fenced
code, and validates local targets/case and migration paths. External URLs and
heading fragments are not fetched or validated. Run from any working directory.
"""
import json
import os
import re
import subprocess
from collections import deque
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
INLINE = re.compile(r'(?<=\])\((<[^>]+>|[^\s)]+)(?:\s+["\'][^\n]*?["\'])?\)')
REFERENCE = re.compile(r'^\s{0,3}\[[^\]]+\]:\s*(<[^>]+>|\S+)')
HTML = re.compile(r'(?:href|src)\s*=\s*["\']([^"\']+)["\']', re.I)
SCHEME = re.compile(r'^[a-zA-Z][\w+.-]*:')


def content_lines(text):
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
            continue
        if fence is None:
            yield number, line


def check():
    listed = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT
    ).decode('utf-8').split('\0')
    files = {Path(p).as_posix() for p in listed if p and (ROOT / p).is_file()}
    directories = {parent.as_posix() for p in files for parent in Path(p).parents}
    documents = sorted(p for p in files if p.endswith('.md'))
    moves = json.loads((ROOT / 'docs/reference/document-paths.json').read_text('utf-8'))
    errors = []
    graph = {p: set() for p in documents}
    local_links = 0
    for document in documents:
        text = (ROOT / document).read_text('utf-8')
        for number, line in content_lines(text):
            targets = [m[1] for m in INLINE.finditer(line)] + [m[1] for m in HTML.finditer(line)]
            definition = REFERENCE.match(line)
            if definition:
                targets.append(definition[1])
            for raw in targets:
                target = raw.strip('<>')
                if not target or target.startswith('#') or SCHEME.match(target) or target.startswith('//'):
                    continue
                path = unquote(urlsplit(target).path)
                candidate = ROOT / path.lstrip('/') if path.startswith('/') else (ROOT / document).parent / path
                lexical = Path(os.path.abspath(candidate))
                if not lexical.resolve().is_relative_to(ROOT):
                    errors.append(f'{document}:{number}: link leaves repository: {target}')
                    continue
                canonical = lexical.relative_to(ROOT).as_posix()
                local_links += 1
                if canonical not in files and canonical not in directories:
                    errors.append(f'{document}:{number}: missing, ignored or wrong-case target: {target}')
                if canonical in graph:
                    graph[document].add(canonical)
            for code in re.findall(r'`([^`]+)`', line):
                if code.replace('\\', '/') in moves:
                    errors.append(f'{document}:{number}: old document path: {code}')
    root_documents = [p.name for p in ROOT.glob('*.md')]
    if root_documents != ['README.md']:
        errors.append('Root Markdown files must be README.md only: ' + ', '.join(sorted(root_documents)))
    for old, new in moves.items():
        if old in files:
            errors.append('Old location still exists: ' + old)
        if new not in files:
            errors.append('Migration destination missing: ' + new)
    reached = set()
    queue = deque(['README.md'])
    while queue:
        document = queue.popleft()
        if document in reached:
            continue
        reached.add(document)
        queue.extend(graph.get(document, ()))
    errors.extend('Document unreachable from README.md: ' + p for p in documents if p not in reached)
    return dict(markdown_files=len(documents),local_links=local_links,reachable_documents=len(reached),
                root_markdown_files=sorted(root_documents),errors=errors,
                scope='Git files; local targets and navigation only; no network or heading-fragment checks')


if __name__ == '__main__':
    result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(bool(result['errors']))
