#!/usr/bin/env python3
"""Run the host-only MOVE16 emitter checks in a disposable build directory."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
(root / 'build').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='move16-test-', dir=root / 'build') as work:
    env = dict(os.environ, EMU68_MOVE16_TEST_WORK=work)
    for script in ('build_probe.py', 'check_emitted.py'):
        subprocess.run([sys.executable, str(Path(__file__).with_name(script))],
                       env=env, check=True)
