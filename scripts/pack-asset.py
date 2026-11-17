#!/usr/bin/env python3
"""把放不进安装包的大游戏打成资源包（zip），供 GitHub Release 托管、运行时下载。

    python3 scripts/pack-asset.py --src app/www/games/great-powers-rts \
        --out dist-assets/great-powers-rts.zip

打完会打印字节数与 sha256，写进 app/www/extras.json 的 bytes / sha256 字段，
下载端据此校验压缩包是否完整。
"""

import argparse
import hashlib
import os
import sys
import time
import zipfile


def iter_files(src):
    for base, dirs, files in os.walk(src):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(base, name)
            # 运行时生成的标记与半截文件不进包
            if name in (".installed.json",) or name.endswith(".part"):
                continue
            yield full, os.path.relpath(full, src).replace(os.sep, "/")


def main(argv=None):
    parser = argparse.ArgumentParser(description="pack a game folder into a release asset")
    parser.add_argument("--src", required=True, help="game folder, e.g. app/www/games/xxx")
    parser.add_argument("--out", required=True, help="zip path, e.g. dist-assets/xxx.zip")
    parser.add_argument("--level", type=int, default=9, help="deflate level (default 9)")
    args = parser.parse_args(argv)

    src = os.path.abspath(args.src)
    out = os.path.abspath(args.out)
    if not os.path.isdir(src):
        sys.stderr.write("source folder not found: %s\n" % src)
        return 1
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    started = time.time()
    raw_total = 0
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=args.level) as zf:
        for full, rel in iter_files(src):
            zf.write(full, rel)
            raw_total += os.path.getsize(full)
            count += 1
            if count % 50 == 0:
                sys.stdout.write("  packed %d files...\n" % count)
                sys.stdout.flush()

    size = os.path.getsize(out)
    digest = hashlib.sha256()
    with open(out, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)

    sys.stdout.write(
        "%s\n  files: %d\n  raw:   %.1f MB\n  zip:   %.1f MB (%.0f%%)\n  bytes: %d\n  sha256: %s\n  took:  %.0fs\n"
        % (out, count, raw_total / 1048576.0, size / 1048576.0,
           100.0 * size / max(1, raw_total), size, digest.hexdigest(), time.time() - started)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
