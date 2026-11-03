"""用公開名片資料集（dataset_business：合成名片 + .txt 標註）評估目前的算法。

    python -m tests.eval_dataset <資料夾> [--n 100] [--show 5]

標註格式（每張圖一個 xxx.jpg.txt）：
    NAM / COM / TIT / MOB / TEL / FAX / EMA / ADD / URL / PC，下一行（tab 開頭）是值，結尾有「|」。
資料集是簡體字，比對前兩邊都轉繁體（opencc）並去掉空白、標點。
"""
import argparse
import random
import re
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

from opencc import OpenCC

from app.parser import phone_key
from app.pipeline import analyze

S2T = OpenCC("s2t")
# 標註欄位 → (我們的欄位, 權重)；權重依重要性：姓名 > 單位 > Email > 電話 > 職稱 > 地址 > 其他
FIELDS = {"NAM": ("name", 5), "COM": ("company", 4), "EMA": ("email", 3), "MOB": ("mobile", 3),
          "TEL": ("phone", 2), "TIT": ("title", 2), "ADD": ("address", 1), "FAX": ("fax", 1), "URL": ("website", 1)}
PREFIX = re.compile(r"^(?:Address|Email|E-mail|Mobile|Tel|Fax|Web|Website|URL|Phone|Mob|Add|Zip|Postcode)\s*[:：]?\s*", re.I)


def read_label(path: Path) -> dict:
    lab, key = {}, None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if re.fullmatch(r"[A-Z]{2,3}", line.strip()):
            key = line.strip()
        elif key and line.strip():
            lab[key] = PREFIX.sub("", line.strip().rstrip("|").strip())
            key = None
    return lab


def norm(s: str) -> str:
    s = S2T.convert(unicodedata.normalize("NFKC", s or "")).lower()
    return re.sub(r"[\s,.()\-·•'’:：|/]", "", s)


def digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def check(field, gt, d):
    if field in ("mobile", "phone", "fax"):
        # 號碼只看數字；手機 / 電話分錯類不算錯（都在 mobile+phone 裡就好），傳真要分對
        pool = d["fax"] if field == "fax" else d["mobile"] + d["phone"]
        g = digits(gt).lstrip("0")
        return any(g and (digits(x).lstrip("0").endswith(g[-8:]) or g.endswith(digits(x).lstrip("0")[-8:] or "x"))
                   for x in pool if len(digits(x)) >= 7)
    if field in ("email", "website"):
        return any(norm(x) == norm(gt) for x in d[field])
    return norm(d.get(field, "")) == norm(gt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--show", type=int, default=5, help="每個欄位列出幾個錯誤例子")
    a = ap.parse_args()
    imgs = sorted(p for p in Path(a.root).rglob("*.jpg") if Path(str(p) + ".txt").exists())
    random.Random(a.seed).shuffle(imgs)
    imgs = imgs[:a.n]
    ok, tot, errs = Counter(), Counter(), {}
    t0 = time.time()
    for i, img in enumerate(imgs, 1):
        lab = read_label(Path(str(img) + ".txt"))
        d = analyze(img.read_bytes())["data"]
        for k, (field, _) in FIELDS.items():
            if k not in lab:
                continue
            tot[field] += 1
            if check(field, lab[k], d):
                ok[field] += 1
            else:
                pred = d[field] if not isinstance(d[field], list) else ", ".join(d[field])
                if field in ("mobile", "phone"):
                    pred = ", ".join(d["mobile"] + d["phone"])
                errs.setdefault(field, []).append((img.name, lab[k], pred))
        if i % 20 == 0:
            print(f"  … {i}/{len(imgs)}（{time.time() - t0:.0f} 秒）", file=sys.stderr)
    print(f"\n{len(imgs)} 張，平均 {(time.time() - t0) / len(imgs):.1f} 秒/張\n")
    w_ok = w_all = 0
    for field, w in sorted({f: w for f, w in FIELDS.values()}.items(), key=lambda x: -x[1]):
        if tot[field]:
            print(f"  {field:<8} {ok[field]:>4}/{tot[field]:<4} {ok[field] / tot[field]:6.1%}   (權重 {w})")
            w_ok += w * ok[field]
            w_all += w * tot[field]
    print(f"\n  依重要性加權：{w_ok / w_all:.1%}")
    for field, es in errs.items():
        print(f"\n[{field}] 錯誤例子：")
        for name, g, p in es[:a.show]:
            print(f"   {name}: 正解 {g!r} ／ 辨識 {p!r}")


if __name__ == "__main__":
    main()
