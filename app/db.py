"""SQLite 儲存：cards 表 + 簡易關鍵字檢索。"""
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA / "cards.db"
FIELDS = ["name", "name_en", "title", "title_en", "department", "department_en", "company", "company_en",
          "address", "address_en", "tax_id", "line_id", "wechat"]
LIST_FIELDS = ["mobile", "phone", "fax", "email", "website", "other"]
POTENTIAL = ["1", "2", "3", "4", "5"]  # 合作可能性 1~5 分；空字串 = 未評估
EXTRA_COLS = {"potential": "TEXT DEFAULT ''", "back_image": "TEXT DEFAULT ''",
              "back_card_image": "TEXT DEFAULT ''", "back_raw": "TEXT DEFAULT '[]'"}


def conn():
    DATA.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT, updated_at TEXT,
        image TEXT, card_image TEXT,
        name TEXT, name_en TEXT, company TEXT, company_en TEXT, title TEXT, email TEXT, mobile TEXT,
        tags TEXT DEFAULT '', note TEXT DEFAULT '',
        data TEXT, raw TEXT, search TEXT)""")
    have = {r["name"] for r in c.execute("PRAGMA table_info(cards)")}
    for col, typ in EXTRA_COLS.items():  # 舊資料庫自動升級
        if col not in have:
            c.execute(f"ALTER TABLE cards ADD COLUMN {col} {typ}")
    c.execute("CREATE INDEX IF NOT EXISTS ix_company ON cards(company)")
    return c


def _search_text(d, tags, note):
    parts = [d.get(k, "") for k in FIELDS] + [" ".join(d.get(k, [])) for k in LIST_FIELDS] + [tags, note]
    s = " ".join(p for p in parts if p).lower()
    # 電話也存一份純數字，搜尋 "0912345" 可命中 "0912-345-678"
    digits = " ".join("".join(ch for ch in n if ch.isdigit()) for k in ("mobile", "phone", "fax") for n in d.get(k, []))
    return s + " " + digits


def _row(r):
    d = json.loads(r["data"])
    return {"id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
            "image": r["image"], "card_image": r["card_image"], "tags": r["tags"], "note": r["note"],
            "potential": r["potential"] or "",
            "back_image": r["back_image"] or "", "back_card_image": r["back_card_image"] or "",
            "data": d, "raw": json.loads(r["raw"] or "[]"), "back_raw": json.loads(r["back_raw"] or "[]")}


def insert(data, raw, image, card_image, back_raw=None, back_image="", back_card_image=""):
    now = datetime.now().isoformat(timespec="seconds")
    with conn() as c:
        cur = c.execute(
            "INSERT INTO cards(created_at,updated_at,image,card_image,back_image,back_card_image,"
            "name,name_en,company,company_en,title,email,mobile,data,raw,back_raw,search)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now, now, image, card_image, back_image, back_card_image,
             data["name"], data["name_en"], data["company"], data["company_en"],
             data["title"] or data["title_en"], ",".join(data["email"]), ",".join(data["mobile"]),
             json.dumps(data, ensure_ascii=False), json.dumps(raw, ensure_ascii=False),
             json.dumps(back_raw or [], ensure_ascii=False), _search_text(data, "", "")))
        return cur.lastrowid


def set_ocr(card_id, raw, back_raw, card_image, back_card_image):
    with conn() as c:
        c.execute("UPDATE cards SET raw=?, back_raw=?, card_image=?, back_card_image=? WHERE id=?",
                  (json.dumps(raw, ensure_ascii=False), json.dumps(back_raw, ensure_ascii=False),
                   card_image, back_card_image, card_id))


def set_back(card_id, back_raw, back_image, back_card_image):
    with conn() as c:
        c.execute("UPDATE cards SET back_raw=?, back_image=?, back_card_image=? WHERE id=?",
                  (json.dumps(back_raw, ensure_ascii=False), back_image, back_card_image, card_id))


def normalize_tags(tags) -> str:
    """標籤（自由索引）→ 存成「金融業,餐廳」。
    - list：每一項就是一個標籤，不再拆開；標籤裡的半形逗號（儲存用的分隔）轉成全形「，」。
    - 字串：資料庫存的格式，只用半形逗號分隔。
    去頭尾空白、去重。"""
    items = [str(t).replace(",", "，") for t in tags] if isinstance(tags, (list, tuple)) else (tags or "").split(",")
    out = []
    for t in items:
        t = t.strip()
        if t and t not in out:
            out.append(t)
    return ",".join(out)


def tag_list(tags: str):
    return [t for t in (tags or "").split(",") if t]


def update(card_id, data, tags="", note="", potential=""):
    tags = normalize_tags(tags)
    now = datetime.now().isoformat(timespec="seconds")
    with conn() as c:
        c.execute(
            "UPDATE cards SET updated_at=?,name=?,name_en=?,company=?,company_en=?,title=?,email=?,mobile=?,"
            "tags=?,note=?,potential=?,data=?,search=? WHERE id=?",
            (now, data["name"], data["name_en"], data["company"], data["company_en"], data["title"] or data["title_en"],
             ",".join(data["email"]), ",".join(data["mobile"]), tags, note, potential,
             json.dumps(data, ensure_ascii=False), _search_text(data, tags, note), card_id))


def get(card_id):
    with conn() as c:
        r = c.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        return _row(r) if r else None


def delete(card_id):
    with conn() as c:
        r = c.execute("SELECT image, card_image, back_image, back_card_image FROM cards WHERE id=?",
                      (card_id,)).fetchone()
        c.execute("DELETE FROM cards WHERE id=?", (card_id,))
        return r


def search(q="", company="", potential=None, limit=200, date_from="", date_to="", sort="new", tags=None,
           tag_mode="all"):
    """q 以空白分隔多個關鍵字，全部命中才回傳（AND）。
    tags：自由索引標籤，多個時要全部都有（AND）；完全比對（「金融業」不會命中「非金融業」）；"__none__" = 尚未加標籤。"""
    sql, args = "SELECT * FROM cards WHERE 1=1", []
    for kw in q.lower().split():
        kw_digits = "".join(ch for ch in kw if ch.isdigit())
        if kw_digits and len(kw_digits) >= 3 and kw_digits == kw.replace("-", "").replace(" ", ""):
            kw = kw_digits
        sql += " AND search LIKE ?"
        args.append(f"%{kw}%")
    if company:
        sql += " AND (company=? OR company_en=?)"
        args += [company, company]
    if potential is not None:  # "" = 未評估
        sql += " AND COALESCE(potential,'')=?"
        args.append(potential)
    conds = []
    for t in tags or []:
        if t == "__none__":
            conds.append("COALESCE(tags,'')=''")
        else:
            conds.append("(',' || COALESCE(tags,'') || ',') LIKE ?")
            args.append(f"%,{t},%")
    if conds:  # all：全部標籤都要有；any：有其中一個就好
        sql += " AND (" + (" OR " if tag_mode == "any" else " AND ").join(conds) + ")"
    if date_from:  # 上傳日期區間（YYYY-MM-DD，含頭尾）
        sql += " AND substr(created_at,1,10) >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND substr(created_at,1,10) <= ?"
        args.append(date_to)
    order = {"old": "id ASC", "potential": "COALESCE(NULLIF(potential,''),'0') DESC, id DESC"}.get(sort, "id DESC")
    sql += f" ORDER BY {order} LIMIT ?"
    args.append(limit)
    with conn() as c:
        return [_row(r) for r in c.execute(sql, args)]


def companies():
    with conn() as c:
        return [{"company": r["co"], "n": r["n"]} for r in c.execute(
            "SELECT COALESCE(NULLIF(company,''), company_en) AS co, COUNT(*) AS n FROM cards "
            "GROUP BY co HAVING co != '' ORDER BY n DESC, co")]


def potentials():
    with conn() as c:
        return {r["p"]: r["n"] for r in c.execute(
            "SELECT COALESCE(potential,'') AS p, COUNT(*) AS n FROM cards GROUP BY p")}


def all_tags():
    """所有標籤與名片數（自由索引列表），多的排前面。"""
    from collections import Counter

    cnt, none = Counter(), 0
    with conn() as c:
        for (t,) in c.execute("SELECT COALESCE(tags,'') FROM cards"):
            lst = tag_list(t)
            cnt.update(lst)
            none += not lst
    return {"tags": [{"tag": k, "n": n} for k, n in sorted(cnt.items(), key=lambda x: (-x[1], x[0]))], "none": none}


def bulk_tags(ids, add=(), remove=()):
    """批次加 / 移除標籤（不動其他欄位，但會更新搜尋文字讓關鍵字也搜得到標籤）。"""
    add, remove = tag_list(normalize_tags(list(add))), set(tag_list(normalize_tags(list(remove))))  # 每一項是一個標籤
    now = datetime.now().isoformat(timespec="seconds")
    with conn() as c:
        for cid in ids:
            r = c.execute("SELECT data, tags, note FROM cards WHERE id=?", (cid,)).fetchone()
            if not r:
                continue
            tags = normalize_tags([t for t in tag_list(r["tags"]) if t not in remove] + add)
            c.execute("UPDATE cards SET tags=?, updated_at=?, search=? WHERE id=?",
                      (tags, now, _search_text(json.loads(r["data"]), tags, r["note"] or ""), cid))
    return len(ids)
