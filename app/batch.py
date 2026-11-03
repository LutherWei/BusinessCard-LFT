"""整頁批次辨識：一張照片排 4×2 張名片，正面一張、反面一張，依位置配對。

    python -m app.batch pic1.jpg pic2.jpg                    # 一組：正面照、反面照
    python -m app.batch p1.jpg p2.jpg p3.jpg p4.jpg          # 多組：正、反、正、反…
    python -m app.batch fronts.jpg --no-back                 # 只有正面
    python -m app.batch pic1.jpg pic2.jpg --mirror           # 翻面時左右對調了
    python -m app.batch pic1.jpg pic2.jpg --rows 3 --cols 3  # 其他排法
    python -m app.batch pic1.jpg pic2.jpg --dry-run          # 只切圖、看預覽，不辨識

結果存進資料庫（網頁上看得到）並輸出 JSON；切割預覽圖存在 --out 資料夾，方便確認有沒有切對。
"""
import argparse
import json
import time
from pathlib import Path

import cv2

from .sheet import encode, pair_sheets, split_sheet


def main():
    ap = argparse.ArgumentParser(description="整頁名片照片（預設 4 列 × 2 欄）→ 切割 → 正反面配對 → 辨識")
    ap.add_argument("photos", nargs="+", help="正面照 反面照 [正面照 反面照 ...]")
    ap.add_argument("--rows", type=int, default=4)
    ap.add_argument("--cols", type=int, default=2)
    ap.add_argument("--no-back", action="store_true", help="每張照片都是正面，沒有反面照")
    ap.add_argument("--mirror", action="store_true", help="反面照左右對調（A 的反面在右邊）")
    ap.add_argument("--out", default="batch_output", help="預覽圖與 JSON 輸出資料夾")
    ap.add_argument("--dry-run", action="store_true", help="只切割並輸出預覽，不辨識、不存資料庫")
    a = ap.parse_args()

    if not a.no_back and len(a.photos) % 2:
        ap.error("照片數量要成對（正面、反面）；只有正面請加 --no-back")
    groups = [(p, None) for p in a.photos] if a.no_back else list(zip(a.photos[::2], a.photos[1::2]))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    for gi, (fp, bp) in enumerate(groups, 1):
        t0 = time.time()
        fronts, fprev = split_sheet(Path(fp).read_bytes(), a.rows, a.cols)
        cv2.imwrite(str(out / f"sheet{gi}_front_preview.jpg"), fprev)
        backs = []
        if bp:
            backs, bprev = split_sheet(Path(bp).read_bytes(), a.rows, a.cols)
            cv2.imwrite(str(out / f"sheet{gi}_back_preview.jpg"), bprev)
        pairs = pair_sheets(fronts, backs, a.cols, a.mirror)
        print(f"\n== 第 {gi} 組：{Path(fp).name}" + (f" + {Path(bp).name}" if bp else "")
              + f"，找到 {len(pairs)} 張名片（切割預覽：{out}/sheet{gi}_*_preview.jpg）")
        if a.dry_run:
            for label, f, b in pairs:
                print(f"   {label}: 正面 {f.shape[1]}×{f.shape[0]}" + (f"，反面 {b.shape[1]}×{b.shape[0]}" if b is not None else "，無反面"))
            continue
        from .main import export_payload, process  # 存進資料庫（和網頁上傳同一套流程）

        for label, f, b in pairs:
            stem = f"{Path(fp).stem}_{label}"
            try:
                card = process(encode(f), stem + ".jpg", encode(b) if b is not None else None, stem + "_back.jpg")
            except Exception as e:
                print(f"   {label}: 失敗 {e}")
                continue
            d = card["data"]
            payload = export_payload(card)
            payload["sheet"], payload["position"] = Path(fp).name, label
            (out / f"{stem}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            summary.append(payload)
            print(f"   {label} → #{card['id']} {d['name'] or d['name_en'] or '（未辨識姓名）'}"
                  f" | {d['company'] or d['company_en']} | {d['title'] or d['title_en']}"
                  f" | {', '.join(d['mobile'] + d['phone'])} | {', '.join(d['email'])}")
        print(f"   耗時 {time.time() - t0:.0f} 秒")
    if summary:
        (out / "all_cards.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n共 {len(summary)} 張，全部結果：{out}/all_cards.json（網頁上也看得到）")


if __name__ == "__main__":
    main()
