"""Build the end-to-end data folder: a source tree of tiny comics and an offline Bangumi file.

Usage: python e2e/fixtures.py <folder>   (the folder is wiped first)
"""
import io
import json
from pathlib import Path
import shutil
import sys
import zipfile

JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20"
    "242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f00000105010101010101000000"
    "00000000000102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191"
    "a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a"
    "737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8"
    "d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbd3ffd9")

SOURCES = [
    "迷宫饭/迷宫饭 Vol.01.zip", "迷宫饭/迷宫饭 Vol.02.zip", "[]/Vol.01.zip",
    # Bare numbers: volumes inferred from the siblings; 70 of them so the history list scrolls virtually.
    *["極道超女/極道超女 {0:02d}.zip".format(number) for number in range(1, 71)],
    # A chapter folder numbered in reading order.
    "[大王饶命][Chap.001-Chap.002]/0002 01 我死了？.zip", "[大王饶命][Chap.001-Chap.002]/0003 02 神奇的系统.zip",
]
SUBJECTS = [
    {"subject_id": 133315, "name": "ダンジョン飯", "name_cn": "迷宫饭", "total_volumes": 14, "writers": ["九井谅子"]},
    {"subject_id": 98253, "name": "結婚指輪物語", "name_cn": "婚戒物语", "total_volumes": 11, "writers": ["めいびい"]},
    {"subject_id": 400001, "name": "極道超女", "name_cn": "极道超女", "total_volumes": 19, "writers": ["作者"]},
    {"subject_id": 400002, "name": "大王饶命", "name_cn": "大王饶命", "total_volumes": None, "writers": ["作者"]},
]


def main(folder: str) -> None:
    root = Path(folder).resolve()
    shutil.rmtree(root, ignore_errors=True)
    (root / "library").mkdir(parents=True)
    for relative in SOURCES:
        path = root / "source" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("001.jpg", JPEG)
            archive.writestr("note.txt", relative)
        path.write_bytes(buffer.getvalue())
    (root / "subjects.json").write_text(json.dumps(SUBJECTS, ensure_ascii=False), encoding="utf-8")
    print(root)


if __name__ == "__main__":
    main(sys.argv[1])
