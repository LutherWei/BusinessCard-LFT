"""產生測試用名片圖片（合成資料，僅供測試）。"""
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent.parent / "samples"
CJK = "/System/Library/Fonts/STHeiti Medium.ttc"
CJK_L = "/System/Library/Fonts/STHeiti Light.ttc"

CARDS = [
    {
        "file": "card_zh_1.jpg",
        "bg": (250, 250, 245),
        "lines": [
            ("光躍科技股份有限公司", CJK, 44, (20, 60, 120), (60, 50)),
            ("Brightleap Technology Co., Ltd.", CJK_L, 24, (80, 80, 80), (60, 105)),
            ("王小明", CJK, 64, (0, 0, 0), (60, 190)),
            ("資深產品經理", CJK_L, 30, (60, 60, 60), (60, 275)),
            ("Senior Product Manager", CJK_L, 24, (90, 90, 90), (60, 315)),
            ("手機：0912-345-678", CJK_L, 26, (30, 30, 30), (560, 200)),
            ("電話：(02) 2712-3456 分機 321", CJK_L, 26, (30, 30, 30), (560, 245)),
            ("傳真：(02) 2712-6543", CJK_L, 26, (30, 30, 30), (560, 290)),
            ("Email：ming.wang@brightleap.com.tw", CJK_L, 26, (30, 30, 30), (560, 335)),
            ("www.brightleap.com.tw", CJK_L, 26, (30, 30, 30), (560, 380)),
            ("105台北市松山區敦化北路100號12樓", CJK_L, 26, (30, 30, 30), (60, 470)),
        ],
    },
    {
        "file": "card_en_1.jpg",
        "bg": (255, 255, 255),
        "lines": [
            ("NORTHWIND LABS INC.", CJK, 40, (180, 30, 30), (60, 50)),
            ("Emily Chen", CJK, 60, (0, 0, 0), (60, 170)),
            ("Director of Business Development", CJK_L, 28, (70, 70, 70), (60, 250)),
            ("M  +886 935 111 222", CJK_L, 26, (30, 30, 30), (60, 340)),
            ("T  +1 (415) 555-0198", CJK_L, 26, (30, 30, 30), (60, 380)),
            ("E  emily.chen@northwindlabs.io", CJK_L, 26, (30, 30, 30), (60, 420)),
            ("W  https://northwindlabs.io", CJK_L, 26, (30, 30, 30), (60, 460)),
            ("500 Howard St, Suite 300, San Francisco, CA 94105", CJK_L, 24, (30, 30, 30), (60, 520)),
        ],
    },
    {
        "file": "card_zh_2.jpg",
        "bg": (240, 246, 255),
        "lines": [
            ("李美華", CJK, 58, (0, 0, 0), (620, 60)),
            ("業務部 協理", CJK_L, 28, (60, 60, 60), (620, 140)),
            ("綠能永續股份有限公司", CJK, 38, (0, 110, 70), (60, 60)),
            ("統一編號：24567890", CJK_L, 24, (60, 60, 60), (60, 115)),
            ("Tel: 04-2358-9900 #18", CJK_L, 26, (30, 30, 30), (60, 300)),
            ("Mobile: 0988 765 432", CJK_L, 26, (30, 30, 30), (60, 345)),
            ("meihua.li@greenpower.com.tw", CJK_L, 26, (30, 30, 30), (60, 390)),
            ("LINE ID: meihua_li", CJK_L, 26, (30, 30, 30), (60, 435)),
            ("407台中市西屯區台灣大道三段99號", CJK_L, 26, (30, 30, 30), (60, 500)),
        ],
    },
]


def main():
    OUT.mkdir(exist_ok=True)
    random.seed(1)
    for c in CARDS:
        img = Image.new("RGB", (1050, 600), c["bg"])
        d = ImageDraw.Draw(img)
        for text, font, size, color, pos in c["lines"]:
            d.text(pos, text, font=ImageFont.truetype(font, size), fill=color)
        # 模擬拍照：輕微旋轉 + 模糊 + 背景
        canvas = Image.new("RGB", (1250, 820), (120, 110, 100))
        img = img.rotate(random.uniform(-3, 3), expand=True, fillcolor=(120, 110, 100))
        canvas.paste(img, (80, 90))
        canvas = canvas.filter(ImageFilter.GaussianBlur(0.6))
        canvas.save(OUT / c["file"], quality=88)
        print("wrote", OUT / c["file"])


if __name__ == "__main__":
    main()
