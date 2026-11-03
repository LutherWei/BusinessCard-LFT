"""名片辨識主流程：OCR（正/反面）→ 解析 → 合併。網頁與評估腳本共用。"""
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from .ocr import run_ocr
from .parser import guess_company_from_email, merge_sides, parse_card


def analyze(front: bytes, back: Optional[bytes] = None) -> dict:
    """回傳 {data, front_lines, back_lines, front_img, back_img}。"""
    if back:  # 正反面互不相關 → 同時辨識
        with ThreadPoolExecutor(2) as ex:
            fut_f, fut_b = ex.submit(run_ocr, front), ex.submit(run_ocr, back)
            (f_lines, f_img), (b_lines, b_img) = fut_f.result(), fut_b.result()
    else:
        (f_lines, f_img), (b_lines, b_img) = run_ocr(front), ([], None)
    data = merge_cards(f_lines, b_lines)
    return {"data": data, "front_lines": f_lines, "back_lines": b_lines, "front_img": f_img, "back_img": b_img}


def merge_cards(front_lines, back_lines=None) -> dict:
    front = parse_card(front_lines, guess_company=False)
    data = merge_sides(front, parse_card(back_lines, guess_company=False)) if back_lines else front
    # 某一面 email 沒認出來時，email 網域可能被當成網站（mail.cpu.edu.tw）
    data["website"] = [w for w in data["website"] if not any(e.endswith("@" + w.lower()) for e in data["email"])]
    return guess_company_from_email(data)
