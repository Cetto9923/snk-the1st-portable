#!/usr/bin/env python3
"""Prepare the pinned optional Swappy static library under this checkout's .local."""
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
VERSION = '2.1.3'
SHA256 = 'a9f83e0cf47d694ed2cea0ae995d5cf7411060d9d4b680610430d03d6b20ea27'
URL = ('https://dl.google.com/dl/android/maven2/androidx/games/games-frame-pacing/'
       f'{VERSION}/games-frame-pacing-{VERSION}.aar')


def prepare():
    directory = ROOT / '.local/third-party' / f'swappy-{VERSION}'
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / f'games-frame-pacing-{VERSION}.aar'
    if not archive.exists():
        descriptor, name = tempfile.mkstemp(prefix='download-', suffix='.aar', dir=directory)
        staging = Path(name)
        with os.fdopen(descriptor, 'wb') as output, urllib.request.urlopen(URL, timeout=60) as response:
            shutil.copyfileobj(response, output)
        if hashlib.sha256(staging.read_bytes()).hexdigest() != SHA256:
            raise RuntimeError(f'Unexpected Swappy archive, retained for inspection at {staging}')
        os.replace(staging, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError(f'Unexpected Swappy archive hash at {archive}')
    unpacked = directory / 'unpacked'
    with zipfile.ZipFile(archive) as contents:
        names = [name for name in contents.namelist()
                 if name.startswith('prefab/modules/swappy_static/') and not name.endswith('/')]
        required = 'prefab/modules/swappy_static/libs/android.arm64-v8a/libswappy_static.a'
        if required not in names:
            raise RuntimeError('Pinned AAR is missing the arm64 static library')
        if not unpacked.exists():
            staging = Path(tempfile.mkdtemp(prefix='unpack-', dir=directory))
            for name in names:
                contents.extract(name, staging)
            os.rename(staging, unpacked)
        for name in names:
            path = unpacked / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(contents.read(name)).digest():
                raise RuntimeError(f'Swappy extraction differs from the pinned AAR at {path}')
    return unpacked


if __name__ == '__main__':
    try:
        print(prepare())
    except Exception as error:
        print(f'Frame pacing dependency preparation failed: {error}', file=sys.stderr)
        raise SystemExit(1)
