"""命令列：名片圖片 → JSON。

    python -m app.cli card1.jpg card2.jpg -o out_dir/   # 每張輸出一個 .json
    python -m app.cli card.jpg --save                    # 同時存入資料庫
"""
import argparse
import json
from pathlib import Path

from .ocr import run_ocr
from .parser import parse_card


def main():
    ap = argparse.ArgumentParser(description="名片圖片 → JSON（本機 OCR，不使用 AI API）")
    ap.add_argument("images", nargs="+")
    ap.add_argument("-o", "--out", help="輸出資料夾；未指定則印到 stdout")
    ap.add_argument("--save", action="store_true", help="同時存入資料庫")
    a = ap.parse_args()
    for p in a.images:
        data = Path(p).read_bytes()
        if a.save:
            from .main import export_payload, process
            result = export_payload(process(data, Path(p).name))
        else:
            lines, _ = run_ocr(data)
            result = {**parse_card(lines), "ocr_lines": [l["text"] for l in lines]}
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if a.out:
            Path(a.out).mkdir(parents=True, exist_ok=True)
            dest = Path(a.out) / (Path(p).stem + ".json")
            dest.write_text(text, encoding="utf-8")
            print("wrote", dest)
        else:
            print(text)


if __name__ == "__main__":
    main()
