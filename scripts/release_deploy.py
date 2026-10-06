"""Choose full GitHub qualification or a faster, code-only VPS deployment.

Defaults to a read-only plan. --execute explicitly starts the selected mode.
The fast command needs an administrator key; the restricted CI key cannot use it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

REPOSITORY = 'Cyphire2025/PassDetection'
HELPER = '/opt/globalconnect-release-tools/release_ci_dispatch.py'


def current_main_revision() -> str:
    output = subprocess.check_output(
        ['git', 'ls-remote', 'https://github.com/' + REPOSITORY + '.git', 'refs/heads/main'],
        text=True, timeout=30,
    ).strip()
    match = re.fullmatch(r'([a-f0-9]{40})\s+refs/heads/main', output)
    if match is None:
        raise ValueError('Could not establish a unique current main revision')
    return match[1]


def deployment_command(mode: str, revision: str, host: str, key: Path | None) -> list[str]:
    if not re.fullmatch('[a-f0-9]{40}', revision):
        raise ValueError('A full lowercase main commit SHA is required')
    if mode == 'full':
        return ['gh', 'workflow', 'run', 'ci.yml', '--repo', REPOSITORY, '--ref', 'main',
                '-f', 'deployment_mode=full', '-f', 'expected_revision=' + revision]
    if mode != 'fast':
        raise ValueError('Choose full or fast explicitly')
    if not re.fullmatch(r'root@[A-Za-z0-9][A-Za-z0-9.-]{0,252}', host) or key is None:
        raise ValueError('Fast deployment requires a root host and separate administrator SSH key')
    return ['ssh', '-i', str(key.resolve()), '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15', host,
            'python3 -B ' + HELPER + ' --operator-fast ' + revision]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('full', 'fast'), required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--host', default='root@200.97.171.206')
    parser.add_argument('--key', type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    command = deployment_command(args.mode, args.revision, args.host, args.key)
    current = current_main_revision()
    if current != args.revision:
        raise ValueError('Selected commit is not current main; inspect the newer commit before choosing')
    print(json.dumps({'mode': args.mode, 'revision': args.revision, 'execute': args.execute,
                      'assurance': 'full CI and signed images' if args.mode == 'full' else
                                   'local build and runtime checks; not full CI qualification',
                      'command': command}), flush=True)
    if args.execute:
        return subprocess.run(command, check=False).returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
