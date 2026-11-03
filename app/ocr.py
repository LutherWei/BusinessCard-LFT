"""OCR：RapidOCR (PaddleOCR PP-OCRv6 ONNX)，本機推論，不用任何雲端 API。"""
import io
import re
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageOps

from .parser import COMMON_SURNAMES

try:  # iPhone HEIC
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

MIN_SCORE = 0.6


@lru_cache(maxsize=1)
def engine():
    from rapidocr import RapidOCR

    return RapidOCR(params={"Global.log_level": "warning"})


@lru_cache(maxsize=1)
def rec_medium():
    """較大的辨識模型（PP-OCRv6 medium）：只用來重認裁切後名片上的文字行，準確度較高（林朵萱 → 林雅萱）。"""
    from rapidocr import ModelType, OCRVersion, RapidOCR

    return RapidOCR(params={"Global.log_level": "warning", "Rec.ocr_version": OCRVersion.PPOCRV6,
                            "Rec.model_type": ModelType.MEDIUM})._load_rec_model()


def _rerecognize(img, lines):
    """用較大的模型重認每一行；兩個模型結果相同（忽略空白）時保留有空白的版本，不同時取信心高的。"""
    from rapidocr.ch_ppocr_rec.typings import TextRecInput
    from rapidocr.utils.process_img import get_rotate_crop_image

    todo = [l for l in lines if not _is_noise(l)]
    if not todo:
        return lines
    crops = [get_rotate_crop_image(img, np.array(l["box"], np.float32)) for l in todo]
    res = rec_medium()(TextRecInput(img=crops))
    for l, t, s in zip(todo, res.txts or [], res.scores or []):
        t = t.strip()
        if not t:
            continue
        same = re.sub(r"\s", "", t) == re.sub(r"\s", "", l["text"])
        if same:
            if t.count(" ") > l["text"].count(" "):
                l["text"] = t
        elif s > l["score"] + 0.02:
            l["text"], l["score"] = t, float(s)
    return lines


@lru_cache(maxsize=1)
def engine_nocls():
    """關掉逐行 180° 自動翻轉的引擎：用來判斷整張圖該往哪邊轉（轉反了文字會亂掉、信心變低）。"""
    from rapidocr import RapidOCR

    return RapidOCR(params={"Global.log_level": "warning", "Global.use_cls": False})


def load_image(data: bytes) -> np.ndarray:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((2400, 2400))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _order(pts):
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], dtype=np.float32)


def crop_card(img: np.ndarray):
    """找出畫面中最大的亮色四邊形（名片）並做透視校正；找不到就回傳原圖。"""
    h, w = img.shape[:2]
    gray = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (7, 7), 0)
    best = None
    for th in (cv2.THRESH_OTSU, None):
        if th is None:
            mask = cv2.dilate(cv2.Canny(gray, 40, 120), np.ones((5, 5), np.uint8), iterations=2)
        else:
            _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | th)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:5]:
            area = cv2.contourArea(c)
            if area < 0.12 * h * w or area > 0.97 * h * w:
                continue
            hull = cv2.convexHull(c)
            approx = cv2.approxPolyDP(hull, 0.02 * cv2.arcLength(hull, True), True)
            if len(approx) != 4:
                rect = cv2.minAreaRect(hull)
                approx = cv2.boxPoints(rect).reshape(-1, 1, 2)
                if area / max(rect[1][0] * rect[1][1], 1) < 0.85:
                    continue
            if best is None or area > best[0]:
                best = (area, approx.reshape(4, 2).astype(np.float32))
        if best:
            break
    if not best:
        return img, False
    src = _order(best[1])
    wd = int(max(np.linalg.norm(src[0] - src[1]), np.linalg.norm(src[3] - src[2])))
    ht = int(max(np.linalg.norm(src[0] - src[3]), np.linalg.norm(src[1] - src[2])))
    if wd < 200 or ht < 120:
        return img, False
    dst = np.array([[0, 0], [wd, 0], [wd, ht], [0, ht]], dtype=np.float32)
    return cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (wd, ht)), True


def _geom(ln):
    xs = [p[0] for p in ln["box"]]
    ys = [p[1] for p in ln["box"]]
    return min(xs), min(ys), max(xs), max(ys)


def _is_tall(ln):
    x0, y0, x1, y1 = _geom(ln)
    return (y1 - y0) > 1.3 * (x1 - x0)


def _merge_rows(lines, vertical=False):
    """先把文字框分成「列」（垂直重疊過半、字高相近），列內由左到右排；
    同列且間距 < 2 倍字高才合併成一行（例如「技術處」「副總」→「技術處 副總」），
    距離更遠的視為左右兩欄（林建宏 | someone@…），各自獨立。直書框不合併。
    vertical=True（直書名片）時閱讀順序是由右到左一欄一欄。"""
    if vertical:
        return [{"text": l["text"], "score": round(l["score"], 3), "box": l["box"]}
                for l in sorted(lines, key=lambda l: (-_geom(l)[2], _geom(l)[1]))]
    rows = []
    for ln in sorted(lines, key=lambda l: _geom(l)[1]):
        x0, y0, x1, y1 = _geom(ln)
        hgt = y1 - y0
        for r in rows:
            if _is_tall(ln) or r["tall"]:
                continue
            rh = r["y1"] - r["y0"]
            ov = min(r["y1"], y1) - max(r["y0"], y0)
            if ov > 0.5 * min(hgt, rh) and max(hgt, rh) <= 1.8 * max(1, min(hgt, rh)):
                r["parts"].append(ln)
                r["y0"], r["y1"] = min(r["y0"], y0), max(r["y1"], y1)
                break
        else:
            rows.append({"parts": [ln], "y0": y0, "y1": y1, "tall": _is_tall(ln)})
    out = []
    for r in sorted(rows, key=lambda r: r["y0"]):
        parts = sorted(r["parts"], key=lambda l: _geom(l)[0])
        segs = [[parts[0]]]
        for p in parts[1:]:
            prev = segs[-1][-1]
            gap = _geom(p)[0] - _geom(prev)[2]
            hh = max(_geom(p)[3] - _geom(p)[1], _geom(prev)[3] - _geom(prev)[1])
            if gap < 1.2 * hh:
                segs[-1].append(p)
            else:
                segs.append([p])
        for seg in segs:
            g = [_geom(p) for p in seg]
            X0, Y0, X1, Y1 = min(a[0] for a in g), min(a[1] for a in g), max(a[2] for a in g), max(a[3] for a in g)
            out.append({"text": " ".join(p["text"] for p in seg), "score": round(min(p["score"] for p in seg), 3),
                        "box": [[X0, Y0], [X1, Y0], [X1, Y1], [X0, Y1]]})
    return out


def _ocr(img, eng=None):
    res = (eng or engine())(img)
    out = []
    if res.txts is not None:
        for b, t, s in zip(res.boxes, res.txts, res.scores):
            if s >= MIN_SCORE and t.strip():
                out.append({"text": t.strip(), "score": float(s), "box": [[float(x), float(y)] for x, y in b]})
    return out


def _weight(lines, tall):
    """某方向（直/橫）文字的份量：信心 × 字數。"""
    return sum(l["score"] * len(l["text"]) for l in lines if len(l["text"]) >= 3 and _is_tall(l) == tall)


def _fix_orientation(img, lines):
    """名片被直拿著拍（文字轉了 90 度）時，大部分文字框會是直的 → 把圖轉正再 OCR 一次。
    但直書名片（陳志明 律師）本來就是直的：轉了反而認不出來，分數比較低就保留原圖。
    回傳 (img, lines, vertical)。"""
    tall_w = _weight(lines, True)
    if tall_w <= _weight(lines, False):
        return img, lines, False
    best, best_w = None, -1
    for rot in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE):
        r = cv2.rotate(img, rot)
        w = _weight(_ocr(r, engine_nocls()), False)  # 不自動翻轉 → 轉錯方向（上下顛倒）會得低分
        if w > best_w:
            best, best_w = r, w
    if best_w < 0.8 * _weight(_ocr(img, engine_nocls()), True):  # 直書名片
        return img, lines, True
    return best, _ocr(best), False


def _fix_upside_down(img, lines):
    """整張名片上下顛倒時（某張名片 英文面），逐行 OCR 仍會自動翻正、文字是對的，但行的順序會反過來。
    用方向分類模型看各行是不是 180°：多數是就把整張圖轉 180° 並轉換座標。"""
    from rapidocr.utils.process_img import get_rotate_crop_image

    wide = [l for l in lines if not _is_tall(l) and len(l["text"]) >= 3][:20]
    if len(wide) < 3:
        return img, lines
    crops = [get_rotate_crop_image(img, np.array(l["box"], np.float32)) for l in wide]
    res = engine()._load_cls_model()(crops).cls_res or []
    flipped = sum(1 for lab, sc in res if lab == "180" and sc > 0.8)
    if flipped <= 0.6 * len(wide):
        return img, lines
    h, w = img.shape[:2]
    out = []
    for l in lines:
        p = [[w - x, h - y] for x, y in l["box"]]
        out.append({**l, "box": [p[2], p[3], p[0], p[1]]})
    return cv2.rotate(img, cv2.ROTATE_180), out


def _main_card(lines, img, vertical=False):
    """去掉背景其他名片的文字：以「主方向」的文字框範圍當作主名片，
    方向相反（直/橫）且落在範圍外的框視為背景雜訊。回傳 (保留的框, 主名片範圍)。"""
    main = [l for l in lines if _is_tall(l) == vertical and len(l["text"]) >= 2]
    if len(main) < 2:
        return lines, None
    hs = sorted(_geom(l)[3] - _geom(l)[1] for l in main)
    pad = hs[len(hs) // 2]
    x0 = min(_geom(l)[0] for l in main) - pad
    y0 = min(_geom(l)[1] for l in main) - pad
    x1 = max(_geom(l)[2] for l in main) + pad
    y1 = max(_geom(l)[3] for l in main) + pad
    keep = []
    for l in lines:
        gx0, gy0, gx1, gy1 = _geom(l)
        cx, cy = (gx0 + gx1) / 2, (gy0 + gy1) / 2
        inside = x0 <= cx <= x1 and y0 <= cy <= y1
        if _is_tall(l) == vertical or (inside and (vertical or re.search("[\u4e00-\u9fff]", l["text"]))
                                       and len(l["text"]) >= 2):
            keep.append(l)  # 直書只保留範圍內的中文（例：臺北市政府 / 青年局 直排 logo）
    # 橫書框也要在主範圍內（範圍由橫書框本身決定，所以只會排除離群很遠的）
    h, w = img.shape[:2]
    box = (max(0, int(x0 - pad)), max(0, int(y0 - pad)), min(w, int(x1 + pad)), min(h, int(y1 + pad)))
    return keep, box


# ---------- 名片裁切：以文字為錨點，往外找名片邊緣 ----------
KEYBOARD_RE = re.compile(
    r"^(?:(?:c?o?m{0,2}m?and|[mnh]and|option|opt|control|ctrl|shift|return|delete|esc|tab|caps\s*lock|fn|alt|"
    r"enter|space)\s*)+$", re.I)
KANA_BOPOMOFO_RE = re.compile(r"[\u3040-\u30ff\u3100-\u312f]")


KEYBOARD_WORDS = ["command", "option", "control", "shift", "return", "delete", "escape", "caps lock", "enter"]


def _is_keyboard_word(t):
    """OCR 常把鍵帽字認錯（commana、cornmand、optlon）→ 用相似度判斷。"""
    from difflib import SequenceMatcher

    w = t.lower().strip()
    return len(w) >= 4 and any(SequenceMatcher(None, w, k).ratio() >= 0.75 for k in KEYBOARD_WORDS)


def _is_noise(l):
    """背景常見雜訊：鍵盤字（option / command / 注音）、單一字元、只有符號。"""
    t = l["text"].strip()
    core = re.sub(r"[\s\W_]", "", t)
    if _is_keyboard_word(t) or (core.isdigit() and len(core) <= 2):  # 「commana」、鍵帽上的「11」
        return True
    if len(core) == 1 and core in COMMON_SURNAMES:  # 直排姓名的姓（林 / 育暄）
        return False
    if len(core) <= 1 or KEYBOARD_RE.match(t):
        return True
    if KANA_BOPOMOFO_RE.search(t) and len(core) <= 6:
        return True
    toks = t.split()
    return len(toks) >= 2 and all(len(x) <= 1 for x in toks)  # 「幺 九」「せ 又 L」鍵帽


def _box_angle(l):
    (x0, y0), (x1, y1) = l["box"][0], l["box"][1]
    return np.degrees(np.arctan2(y1 - y0, x1 - x0))


def _seeds(lines, vertical):
    """主名片的文字框：去雜訊、取主方向、再取最大的一群（避免背景另一張名片）。"""
    cand = [l for l in lines if not _is_noise(l) and _is_tall(l) == vertical]
    if len(cand) < 2:
        return cand
    hs = sorted(_geom(l)[3] - _geom(l)[1] if not vertical else _geom(l)[2] - _geom(l)[0] for l in cand)
    mh = hs[len(hs) // 2]

    def near(a, b, d):
        ga, gb = _geom(a), _geom(b)
        dx = max(0, max(ga[0], gb[0]) - min(ga[2], gb[2]))
        dy = max(0, max(ga[1], gb[1]) - min(ga[3], gb[3]))
        return dx <= d and dy <= d
    # 很短又孤立的字（鍵帽、logo 碎片）不當成名片文字的錨點
    cand = [l for l in cand if len(re.sub(r"[\s\W_]", "", l["text"])) > 3
            or any(o is not l and near(l, o, 3 * mh) for o in cand)]
    if len(cand) < 2:
        return cand
    link = 8.0 * mh
    n = len(cand)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    g = [_geom(l) for l in cand]
    for a in range(n):
        for b in range(a + 1, n):
            dx = max(0, max(g[a][0], g[b][0]) - min(g[a][2], g[b][2]))
            dy = max(0, max(g[a][1], g[b][1]) - min(g[a][3], g[b][3]))
            if dx <= link and dy <= link:
                parent[find(a)] = find(b)
    groups = {}
    for a in range(n):
        groups.setdefault(find(a), []).append(a)
    best = max(groups.values(), key=lambda idx: sum(len(cand[i]["text"]) for i in idx))
    return [cand[i] for i in best]


def _edge(profile_fn, start, stop, step):
    """從 start 往 stop 掃，回傳第一個「橫跨大部分寬度」的強邊緣位置。"""
    for pos in range(start, stop, step):
        if profile_fn(pos) > 0.45:
            return pos
    return None


def _crop_by_text(img, seeds):
    """用主名片文字當錨點：先依文字角度轉正，再從文字範圍往四周找名片邊緣（一整條直線的強梯度）。
    手指只會擋住邊緣的一部分，所以用「該列有多少比例是邊緣」判斷。回傳 (裁好的圖, 是否成功)。"""
    if len(seeds) < 2:
        return img, False, None
    angs = [_box_angle(l) for l in seeds if len(l["text"]) >= 4] or [0.0]
    ang = float(np.median(angs))
    if abs(ang) > 30:
        ang = 0.0
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    rot = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
    pts = np.array([p for l in seeds for p in l["box"]], dtype=np.float32)
    pts = cv2.transform(pts.reshape(-1, 1, 2), M).reshape(-1, 2)
    x0, y0 = pts.min(0).astype(int)
    x1, y1 = pts.max(0).astype(int)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w - 1, x1), min(h - 1, y1)
    hs = sorted(_geom(l)[3] - _geom(l)[1] for l in seeds)
    lh = max(8, hs[len(hs) // 2])
    gray = cv2.GaussianBlur(cv2.cvtColor(rot, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    gy = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    gx = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
    thr = max(25.0, float(np.percentile(np.maximum(gx, gy), 90)))
    ey, ex = gy > thr, gx > thr
    # 某一列/行在文字範圍內，有多少比例是強邊緣（容許 ±2 px 的歪斜）
    row = lambda y: ey[max(0, y - 2):y + 3, x0:x1 + 1].any(0).mean()
    col = lambda x: ex[y0:y1 + 1, max(0, x - 2):x + 3].any(1).mean()
    reach_y = int(max(3 * lh, 0.6 * (y1 - y0)))
    reach_x = int(max(3 * lh, 0.4 * (x1 - x0)))
    gap = int(0.3 * lh)  # 避開文字本身的筆畫
    top = _edge(row, y0 - gap, max(0, y0 - reach_y), -1)
    bot = _edge(row, y1 + gap, min(h, y1 + reach_y), 1)
    lef = _edge(col, x0 - gap, max(0, x0 - reach_x), -1)
    rig = _edge(col, x1 + gap, min(w, x1 + reach_x), 1)
    pad = int(1.2 * lh)  # 沒找到邊緣的那一側：文字範圍外留一點
    cy0 = top if top is not None else max(0, y0 - pad)
    cy1 = bot if bot is not None else min(h, y1 + pad)
    cx0 = lef if lef is not None else max(0, x0 - pad)
    cx1 = rig if rig is not None else min(w, x1 + pad)
    crop = rot[cy0:cy1, cx0:cx1]
    return crop, crop.size > 0, (M, (cx0, cy0, cx1, cy1))


def run_ocr(data: bytes):
    """回傳 (lines, card_bgr)。lines 為合併後的文字列。
    流程：整張 OCR → 判斷方向（直拿 / 直書）→ 用文字找出主名片並裁切轉正 → 在乾淨的名片上再 OCR 一次。"""
    img = load_image(data)
    raw = _ocr(img)
    img, raw, vertical = _fix_orientation(img, raw)
    if not vertical:
        img, raw = _fix_upside_down(img, raw)
    seeds = _seeds(raw, vertical)
    if seeds:  # 只重認主名片附近的字（省時間）
        g = [_geom(l) for l in seeds]
        pad = 3 * max(1, sorted(b[3] - b[1] for b in g)[len(g) // 2])
        X0, Y0 = min(b[0] for b in g) - pad, min(b[1] for b in g) - pad
        X1, Y1 = max(b[2] for b in g) + pad, max(b[3] for b in g) + pad
        near = [l for l in raw if X0 <= (_geom(l)[0] + _geom(l)[2]) / 2 <= X1 and Y0 <= (_geom(l)[1] + _geom(l)[3]) / 2 <= Y1]
        _rerecognize(img, near)
    card, ok, geo = _crop_by_text(img, seeds)
    if ok:
        M, (cx0, cy0, cx1, cy1) = geo
        lines = []
        for l in raw:  # 原 OCR 結果轉到裁切後座標；中心落在名片內的才留
            pts = cv2.transform(np.array(l["box"], np.float32).reshape(-1, 1, 2), M).reshape(-1, 2)
            cx, cy = pts.mean(0)
            if cx0 <= cx <= cx1 and cy0 <= cy <= cy1:
                lines.append({**l, "box": [[float(x - cx0), float(y - cy0)] for x, y in pts]})
    else:
        card, lines = img, raw
    lines = [l for l in lines if not _is_noise(l)]
    lines, box = _main_card(lines, card, vertical)
    if box and not ok:
        bx0, by0, bx1, by1 = box
        card = card[by0:by1, bx0:bx1]
        for l in lines:
            l["box"] = [[x - bx0, y - by0] for x, y in l["box"]]
    return _merge_rows(lines, vertical), card
