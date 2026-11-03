"""真實名片評估：對 ground_truth.json 跑完整流程（OCR + 解析 + 正反面合併），逐欄位比對。

    python -m tests.eval_real            # 全部
    python -m tests.eval_real cna_chen   # 只跑某幾張，並印出 OCR 文字
    python -m tests.eval_real --set batch2   # 用 ground_truth_batch2.json
    python -m tests.eval_real --set all      # 全部
正解欄位可用 "A | B" 表示多個可接受答案。
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

from app.parser import phone_key
from app.pipeline import analyze

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ["name", "name_en", "company", "company_en", "email", "mobile", "phone",
          "title", "title_en", "department", "address", "address_en", "fax", "website"]
# 重要性權重：姓名 > 單位 > Email > 電話 > 職稱 / 部門 > 地址 > 其他
WEIGHT = {"name": 5, "name_en": 4, "company": 4, "company_en": 3, "email": 3, "mobile": 3, "phone": 2,
          "title": 2, "title_en": 1, "department": 1, "address": 1, "address_en": 1, "fax": 1, "website": 1}
LOOSE = {"title", "title_en", "department"}  # 正解是預測的子字串即可（名片上常有多個職稱）


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower().replace("台", "臺").replace("内", "內")
    return re.sub(r"[\s,.()\-·•'’]", "", s)


def match(field, pred, gt):
    if isinstance(gt, list):
        key = phone_key if field in ("mobile", "phone", "fax") else norm
        return {key(x) for x in pred} == {key(x) for x in gt}
    if " | " in gt:
        return any(match(field, pred, alt) for alt in gt.split(" | "))
    p, g = norm(pred), norm(gt)
    if field in LOOSE and g and g in p and len(p) <= len(g) * 3:
        return True
    return p == g


def main():
    args = sys.argv[1:]
    which = "base"
    if "--set" in args:
        i = args.index("--set")
        which = args[i + 1]
        args = args[:i] + args[i + 2:]
    files = {"base": ["ground_truth.json"], "batch2": ["ground_truth_batch2.json"],
             "all": ["ground_truth.json", "ground_truth_batch2.json"]}[which]
    only = set(args)
    cases = [c for f in files for c in json.loads((ROOT / "tests" / f).read_text()) if not only or c["id"] in only]
    total = ok = 0
    per_field = {f: [0, 0] for f in FIELDS}
    for c in cases:
        res = analyze((ROOT / c["front"]).read_bytes(), (ROOT / c["back"]).read_bytes() if c.get("back") else None)
        d = res["data"]
        if only:
            for side in ("front_lines", "back_lines"):
                print(f"  [{side}]", " | ".join(l["text"] for l in res[side]))
        bad = []
        for f in FIELDS:
            gt = c["expect"].get(f, [] if f in ("mobile", "phone", "fax", "email", "website") else "")
            good = match(f, d.get(f, ""), gt)
            per_field[f][0] += good
            per_field[f][1] += 1
            total += 1
            ok += good
            if not good:
                bad.append(f"{f}: {d.get(f)!r} ≠ {gt!r}")
        print(f"{'✅' if not bad else '❌'} {c['id']}  ({len(FIELDS) - len(bad)}/{len(FIELDS)})")
        for b in bad:
            print("     ", b)
    print(f"\n總計 {ok}/{total} = {ok / total:.0%}")
    w_ok = sum(WEIGHT[f] * a for f, (a, n) in per_field.items())
    w_all = sum(WEIGHT[f] * n for f, (a, n) in per_field.items())
    print(f"依重要性加權（姓名 5、公司 4、Email 3…）：{w_ok / w_all:.1%}")
    print("各欄位（依重要性）：" + "  ".join(f"{f}:{a}/{n}" for f, (a, n) in per_field.items()))


if __name__ == "__main__":
    main()
