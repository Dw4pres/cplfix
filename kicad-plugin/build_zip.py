#!/usr/bin/env python3
"""Build the CPLfix PCM package zip (the exact archive layout KiCad's
Plugin and Content Manager expects) and validate metadata.json against
the vendored PCM v1 schema.

Usage: python3 build_zip.py
Output: dist/cplfix-1.0.0.zip (+ its SHA-256 and sizes, the numbers the
submission copy of the metadata needs).

Archive layout (dev-docs.kicad.org/en/addons, Python plugins):
    cplfix-1.0.0.zip
    |- plugins/cplfix.py
    |- plugins/cplfix_core.py
    |- plugins/__init__.py
    |- resources/icon.png
    |- metadata.json        (archive copy: NO download_* keys — those
                             only go in metadata.submit.json)
"""
import hashlib
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "1.0.0"

FILES = [
    ("plugins/cplfix.py", "plugins/cplfix.py"),
    ("plugins/cplfix_core.py", "plugins/cplfix_core.py"),
    ("plugins/__init__.py", "plugins/__init__.py"),
    ("resources/icon.png", "resources/icon.png"),
    ("metadata.json", "metadata.json"),
]


def main():
    import jsonschema

    with open(os.path.join(HERE, "schemas", "pcm.v1.schema.json")) as f:
        schema = json.load(f)
    with open(os.path.join(HERE, "metadata.json")) as f:
        meta = json.load(f)
    jsonschema.validate(meta, schema)
    assert "download_url" not in json.dumps(meta), (
        "download_* keys must NOT be in the archive metadata.json "
        "(they only belong in metadata.submit.json)"
    )
    print("metadata.json validates against PCM v1 schema")

    os.makedirs(os.path.join(HERE, "dist"), exist_ok=True)
    zip_path = os.path.join(HERE, "dist", "cplfix-%s.zip" % VERSION)
    install_size = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for src, arc in FILES:
            p = os.path.join(HERE, src)
            install_size += os.path.getsize(p)
            z.write(p, arc)
    digest = hashlib.sha256(open(zip_path, "rb").read()).hexdigest()
    size = os.path.getsize(zip_path)
    print("wrote %s" % zip_path)
    print("download_sha256: %s" % digest)
    print("download_size:   %d" % size)
    print("install_size:    %d" % install_size)
    print("Copy these three numbers into metadata.submit.json, then submit "
          "that file to the KiCad addons repository.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
