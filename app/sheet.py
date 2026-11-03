"""整頁拍照：一張照片排 rows × cols 張名片（預設 4 列 × 2 欄），切成一張一張。

    A B
    C D      正面照片 pic1：A..H
    E F      反面照片 pic2：A'..H'（同位置配對）
    G H

切法：整張照片先做一次快速 OCR，找出所有文字框，再在「沒有文字跨過」的空隙下刀，
不靠桌面顏色、名片稍微歪或沒排整齊也可以。照片拿反（橫拍、上下顛倒）會先轉正。
"""
import io
import string

import cv2
import numpy as np
from PIL import Image, ImageOps

from .ocr import _geom, _is_noise, _is_tall, _ocr, _weight, engine, engine_nocls

ANALYZE_SIDE = 1800  # 分析用的縮圖長邊；切的時候用原圖解析度


def load_full(data: bytes) -> np.ndarray:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((4800, 4800))  # 保留高解析度（每張名片約佔 1/8）
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _small(img):
    s = ANALYZE_SIDE / max(img.shape[:2])
    return cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img.copy()


def _orient(img):
    """整張照片轉正：大部分文字是直的 → 轉 90°；大部分行被判定上下顛倒 → 轉 180°。回傳轉好的原圖。"""
    small = _small(img)
    lines = [l for l in _ocr(small) if not _is_noise(l)]
    if _weight(lines, True) > _weight(lines, False):
        best, best_w = None, -1
        for rot in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE):
            w = _weight(_ocr(cv2.rotate(small, rot), engine_nocls()), False)  # 不自動翻正 → 轉錯方向會得低分
            if w > best_w:
                best, best_w = rot, w
        img, small = cv2.rotate(img, best), cv2.rotate(small, best)
        lines = [l for l in _ocr(small) if not _is_noise(l)]
    # 上下顛倒：用方向分類模型看各行
    from rapidocr.utils.process_img import get_rotate_crop_image

    wide = [l for l in lines if not _is_tall(l) and len(l["text"]) >= 3][:30]
    if len(wide) >= 4:
        crops = [get_rotate_crop_image(small, np.array(l["box"], np.float32)) for l in wide]
        res = engine()._load_cls_model()(crops).cls_res or []
        if sum(1 for lab, sc in res if lab == "180" and sc > 0.8) > 0.6 * len(wide):
            img, small = cv2.rotate(img, cv2.ROTATE_180), cv2.rotate(small, cv2.ROTATE_180)
            lines = [l for l in _ocr(small) if not _is_noise(l)]
    return img, small, lines


def _best_cut(spans, lo, hi, expect, size):
    """在 [lo, hi] 找一刀：跨過的文字越少越好，同樣少就選空隙最寬處的中間，再其次靠近預期位置。"""
    lo, hi = max(1, int(lo)), min(size - 1, int(hi))
    if hi <= lo:
        return int(expect)
    cost = np.zeros(hi - lo + 1)
    for a, b, w in spans:
        ia, ib = max(lo, int(a)), min(hi, int(b))
        if ia <= ib:
            cost[ia - lo:ib - lo + 1] += w
    best = cost.min()
    ok = np.where(cost <= best + 1e-6)[0]
    runs, start = [], ok[0]  # 最低成本的連續區段
    for p, q in zip(ok, ok[1:]):
        if q != p + 1:
            runs.append((start, p))
            start = q
    runs.append((start, ok[-1]))
    run = max(runs, key=lambda r: (r[1] - r[0], -abs((r[0] + r[1]) / 2 + lo - expect)))
    return int(lo + (run[0] + run[1]) / 2)


def _cuts(spans, lo, hi, n):
    """在 [lo, hi]（名片文字的範圍）內切成 n 段：每一刀在預期位置附近、跨過文字最少的空隙。"""
    step = (hi - lo) / n
    return [_best_cut(spans, lo + (k - 0.4) * step, lo + (k + 0.4) * step, lo + k * step, int(hi) + 2)
            for k in range(1, n)]


def split_sheet(data: bytes, rows: int = 4, cols: int = 2):
    """回傳 (cells, preview)。cells: [(標籤, 名片圖, 文字行數)]，依閱讀順序 A, B, C...；
    preview: 畫上切線與標籤的縮圖，方便確認。
    先切欄、再「每一欄各自」切列（左右兩欄不一定對齊）；切點以名片文字的實際範圍為準
    （名片沒有排滿整張照片也可以）。"""
    img, small, lines = _orient(load_full(data))
    sh, sw = small.shape[:2]
    if sw > sh and rows > cols:  # 轉正後是橫的 → 名片排成 cols 列 × rows 欄
        rows, cols = cols, rows
    g = [_geom(l) for l in lines]
    if not g:
        return [], small
    pad = 0.03 * max(sw, sh)
    X0, X1 = max(0, min(b[0] for b in g) - pad), min(sw, max(b[2] for b in g) + pad)
    xs = [(b[0], b[2], b[3] - b[1]) for b in g]
    xb = [0] + _cuts(xs, X0, X1, cols) + [sw]
    scale = img.shape[1] / sw
    labels = string.ascii_uppercase
    cells, preview = [], small.copy()
    col_rows = []
    for c in range(cols):
        mine = [b for b in g if xb[c] <= (b[0] + b[2]) / 2 < xb[c + 1]]
        if mine:
            Y0, Y1 = max(0, min(b[1] for b in mine) - pad), min(sh, max(b[3] for b in mine) + pad)
            ys = [(b[1], b[3], b[2] - b[0]) for b in mine]
            col_rows.append([0] + _cuts(ys, Y0, Y1, rows) + [sh])
        else:
            col_rows.append([round(k * sh / rows) for k in range(rows + 1)])
    for r in range(rows):
        for c in range(cols):
            x0, x1 = xb[c], xb[c + 1]
            y0, y1 = col_rows[c][r], col_rows[c][r + 1]
            n_text = sum(1 for b in g if x0 <= (b[0] + b[2]) / 2 < x1 and y0 <= (b[1] + b[3]) / 2 < y1)
            label = labels[r * cols + c]
            crop = img[int(y0 * scale):int(y1 * scale), int(x0 * scale):int(x1 * scale)]
            cells.append((label, crop, n_text))
            color = (0, 160, 0) if n_text else (0, 0, 220)
            cv2.rectangle(preview, (int(x0) + 3, int(y0) + 3), (int(x1) - 3, int(y1) - 3), color, 4)
            cv2.putText(preview, label if n_text else label + " (no text)", (int(x0) + 18, int(y0) + 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.8, color, 5)
    return cells, preview


def pair_sheets(fronts, backs, cols: int = 2, mirror: bool = False):
    """依位置配對正反面 → [(標籤, 正面圖, 反面圖 or None)]。
    mirror=True：翻面時左右對調（A 的反面在 B 的位置）。
    只有 logo 沒字的一面也保留（Coca-Cola、TJW）；兩面都沒有字才當空位。"""
    back_map = {}
    for label, crop, n in backs:
        idx = string.ascii_uppercase.index(label)
        if mirror:
            r, c = divmod(idx, cols)
            idx = r * cols + (cols - 1 - c)
        back_map[string.ascii_uppercase[idx]] = (crop, n)
    out = []
    for label, crop, n in fronts:
        b, bn = back_map.get(label, (None, 0))
        if n + bn == 0:
            continue
        out.append((label, crop, b if bn else None))
    return out


def encode(img) -> bytes:
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()
