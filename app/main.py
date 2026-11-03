"""FastAPI 後端：上傳名片 → OCR → 解析 → 存 DB；提供檢索、編輯、匯出 JSON。"""
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

import cv2
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .ocr import run_ocr
from .parser import merge_sides, parse_card
from .pipeline import analyze, merge_cards

ROOT = Path(__file__).resolve().parent
IMG_DIR = db.DATA / "images"
JSON_DIR = db.DATA / "json"
for d in (IMG_DIR, JSON_DIR):
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="名片管理系統")


def export_payload(card):
    return {"id": card["id"], **card["data"], "potential": int(card["potential"]) if card["potential"] else None,  # 1~5，null = 未評估
            "tags": db.tag_list(card["tags"]), "note": card["note"],
            "uploaded_at": card["created_at"], "updated_at": card["updated_at"],
            "image": card["image"], "back_image": card["back_image"],
            "ocr_lines": [r["text"] for r in card["raw"]],
            "ocr_lines_back": [r["text"] for r in card["back_raw"]]}


def write_json(card_id):
    card = db.get(card_id)
    (JSON_DIR / f"card_{card_id}.json").write_text(
        json.dumps(export_payload(card), ensure_ascii=False, indent=2), encoding="utf-8")
    return card


def ocr_and_save(data: bytes, filename: str):
    """OCR 一面並存原圖 + 裁切圖；回傳 (lines, 原圖檔名, 裁切圖檔名)。"""
    lines, card_img = run_ocr(data)
    stem = uuid.uuid4().hex[:12]
    ext = Path(filename).suffix.lower() or ".jpg"
    (IMG_DIR / f"{stem}{ext}").write_bytes(data)
    cv2.imwrite(str(IMG_DIR / f"{stem}_card.jpg"), card_img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return lines, f"{stem}{ext}", f"{stem}_card.jpg"


def process(data: bytes, filename: str, back: Optional[bytes] = None, back_name: str = ""):
    if back:  # 正反面互不相關 → 同時辨識（實測約快 11%）
        with ThreadPoolExecutor(2) as ex:
            f = ex.submit(ocr_and_save, data, filename)
            b = ex.submit(ocr_and_save, back, back_name or "back.jpg")
            (lines, img, card_img), (b_lines, b_img, b_card) = f.result(), b.result()
    else:
        lines, img, card_img = ocr_and_save(data, filename)
        b_lines, b_img, b_card = [], "", ""
    cid = db.insert(merge_cards(lines, b_lines), lines, img, card_img, b_lines, b_img, b_card)
    return write_json(cid)


@app.post("/api/cards")
async def upload(front: List[UploadFile] = File(None), back: List[UploadFile] = File(None),
                 files: List[UploadFile] = File(None)):
    """front[i] 與 back[i] 依順序配對成同一張名片；back 可省略。files 為舊版相容參數（只有正面）。"""
    fronts = (front or []) + (files or [])
    backs = back or []
    if not fronts:
        raise HTTPException(400, "請至少上傳正面")
    out = []
    for i, f in enumerate(fronts):
        b = backs[i] if i < len(backs) else None
        try:
            out.append(await run_in_threadpool(
                process, await f.read(), f.filename or "front.jpg",
                await b.read() if b else None, b.filename if b else ""))
        except Exception as e:  # 單張失敗不影響其他張
            out.append({"error": str(e), "filename": f.filename})
    return out


def process_sheet(front_data: bytes, back_data: Optional[bytes], rows: int, cols: int, mirror: bool, tag: str):
    """整頁照片：切成 rows×cols 張 → 依位置配對正反面 → 每張走一般流程存進資料庫。"""
    from .sheet import encode, pair_sheets, split_sheet

    fronts, fprev = split_sheet(front_data, rows, cols)
    backs, bprev = split_sheet(back_data, rows, cols) if back_data else ([], None)
    previews = {}
    for side, img in (("front", fprev), ("back", bprev)):
        if img is not None:
            name = f"sheet_{uuid.uuid4().hex[:10]}_{side}.jpg"
            cv2.imwrite(str(IMG_DIR / name), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            previews[side] = f"/images/{name}"
    cards = []
    for label, f, b in pair_sheets(fronts, backs, cols, mirror):
        try:
            card = process(encode(f), f"{tag}_{label}.jpg", encode(b) if b is not None else None, f"{tag}_{label}_back.jpg")
            cards.append({"position": label, "id": card["id"], "name": card["data"]["name"] or card["data"]["name_en"]})
        except Exception as e:  # 單張失敗不影響其他張
            cards.append({"position": label, "error": str(e)})
    return {"previews": previews, "cards": cards}


@app.post("/api/sheets")
async def upload_sheets(front: List[UploadFile] = File(...), back: List[UploadFile] = File(None),
                        rows: int = Form(4), cols: int = Form(2), mirror: bool = Form(False)):
    """整頁模式：front[i] 是第 i 張正面整頁照、back[i] 是對應的反面整頁照（可省略）。"""
    backs = back or []
    out = []
    for i, f in enumerate(front):
        b = backs[i] if i < len(backs) else None
        tag = Path(f.filename or f"sheet{i + 1}").stem
        try:
            out.append({"sheet": f.filename, **await run_in_threadpool(
                process_sheet, await f.read(), await b.read() if b else None, rows, cols, mirror, tag)})
        except Exception as e:
            out.append({"sheet": f.filename, "error": str(e), "cards": []})
    return out


@app.post("/api/cards/{card_id}/back")
async def upload_back(card_id: int, file: UploadFile = File(...)):
    """替既有名片補上（或更換）反面。"""
    card = db.get(card_id)
    if not card:
        raise HTTPException(404)
    lines, img, card_img = await run_in_threadpool(ocr_and_save, await file.read(), file.filename or "back.jpg")
    for name in (card["back_image"], card["back_card_image"]):
        if name:
            (IMG_DIR / name).unlink(missing_ok=True)
    db.set_back(card_id, lines, img, card_img)
    db.update(card_id, merge_sides(card["data"], parse_card(lines, guess_company=False)),
              card["tags"], card["note"], card["potential"])
    return write_json(card_id)


@app.post("/api/cards/{card_id}/reparse")
def reparse(card_id: int):
    """用目前的 OCR + 解析規則，從原始照片重跑；標籤、備註、合作可能性保留，手動修改的欄位會被覆蓋。"""
    card = db.get(card_id)
    if not card:
        raise HTTPException(404)
    front = (IMG_DIR / card["image"]).read_bytes()
    back = (IMG_DIR / card["back_image"]).read_bytes() if card["back_image"] else None
    res = analyze(front, back)
    stem = Path(card["image"]).stem
    cv2.imwrite(str(IMG_DIR / f"{stem}_card.jpg"), res["front_img"], [cv2.IMWRITE_JPEG_QUALITY, 88])
    b_card = ""
    if back:
        b_card = f"{Path(card['back_image']).stem}_card.jpg"
        cv2.imwrite(str(IMG_DIR / b_card), res["back_img"], [cv2.IMWRITE_JPEG_QUALITY, 88])
    db.set_ocr(card_id, res["front_lines"], res["back_lines"], f"{stem}_card.jpg", b_card)
    db.update(card_id, res["data"], card["tags"], card["note"], card["potential"])
    return write_json(card_id)


@app.get("/api/cards")
def list_cards(q: str = "", company: str = "", potential: Optional[str] = None,
               date_from: str = "", date_to: str = "", sort: str = "new", tag: List[str] = Query(None),
               tag_mode: str = "all"):
    return db.search(q, company, potential, date_from=date_from, date_to=date_to, sort=sort, tags=tag, tag_mode=tag_mode)


@app.get("/api/tags")
def list_tags():
    """自由索引：所有標籤與名片數。"""
    return db.all_tags()


class BulkTags(BaseModel):
    ids: List[int]
    add: List[str] = []
    remove: List[str] = []


@app.post("/api/cards/tags")
def bulk_tags(body: BulkTags):
    """批次加 / 移除標籤：{"ids": [1,2], "add": ["金融業"], "remove": ["餐廳"]}。"""
    n = db.bulk_tags(body.ids, body.add, body.remove)
    for cid in body.ids:
        if db.get(cid):
            write_json(cid)
    return {"updated": n}


@app.get("/api/potentials")
def list_potentials():
    return db.potentials()


@app.get("/api/companies")
def list_companies():
    return db.companies()


@app.get("/api/cards/{card_id}")
def get_card(card_id: int):
    c = db.get(card_id)
    if not c:
        raise HTTPException(404)
    return c


class CardUpdate(BaseModel):
    data: dict
    tags: str = ""
    note: str = ""
    potential: str = ""


@app.put("/api/cards/{card_id}")
def update_card(card_id: int, body: CardUpdate):
    old = db.get(card_id)
    if not old:
        raise HTTPException(404)
    merged = {**old["data"], **body.data}
    for k in db.LIST_FIELDS:
        if isinstance(merged.get(k), str):
            merged[k] = [x.strip() for x in merged[k].split(",") if x.strip()]
    if body.potential not in db.POTENTIAL + [""]:
        raise HTTPException(400, "合作可能性需為 1~5 分或空白（未評估）")
    db.update(card_id, merged, body.tags, body.note, body.potential)
    return write_json(card_id)


@app.delete("/api/cards/{card_id}")
def delete_card(card_id: int):
    r = db.delete(card_id)
    if r:
        for name in (r["image"], r["card_image"], r["back_image"], r["back_card_image"]):
            if name:
                (IMG_DIR / name).unlink(missing_ok=True)
        (JSON_DIR / f"card_{card_id}.json").unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/cards/{card_id}/json")
def download_json(card_id: int):
    c = db.get(card_id)
    if not c:
        raise HTTPException(404)
    return JSONResponse(export_payload(c),
                        headers={"Content-Disposition": f'attachment; filename="card_{card_id}.json"'})


@app.get("/api/export.json")
def export_all(q: str = "", company: str = "", potential: Optional[str] = None,
               date_from: str = "", date_to: str = "", sort: str = "new", tag: List[str] = Query(None),
               tag_mode: str = "all"):
    rows = db.search(q, company, potential, limit=100000, date_from=date_from, date_to=date_to, sort=sort, tags=tag,
                     tag_mode=tag_mode)
    return JSONResponse([export_payload(c) for c in rows],
                        headers={"Content-Disposition": 'attachment; filename="cards.json"'})


app.mount("/images", StaticFiles(directory=IMG_DIR), name="images")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")
