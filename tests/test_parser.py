"""解析規則回歸測試：python -m pytest tests/ -q"""
import pytest

from app.parser import parse_card, phone_key


def lines(*texts):
    """把文字依序排成一行一行（字高相同）。"""
    return [{"text": t, "box": [[0, i * 50], [300, i * 50], [300, i * 50 + 40], [0, i * 50 + 40]]}
            for i, t in enumerate(texts)]


def pick(d, *keys):
    return {k: d[k] for k in keys}


# (輸入行, 期望欄位)
CASES = [
    # 英文整字比對：Principal 不再命中 inc、Group Leader 是職稱
    (("王大明", "Principal Engineer", "0912-345-678"), {"company_en": "", "title_en": "Principal Engineer"}),
    (("林小華", "Group Leader", "Acme Corp."), {"company_en": "Acme Corp.", "title_en": "Group Leader"}),
    (("Jane Doe", "Bank Manager", "Bank of Taiwan"), {"company_en": "Bank of Taiwan", "title_en": "Bank Manager"}),
    (("ACME INTERNATIONAL INC.",), {"company_en": "ACME INTERNATIONAL INC."}),
    (("Acme International",), {"company_en": "Acme International"}),
    # 新增中文強關鍵字
    (("張三", "富邦金控"), {"company": "富邦金控"}),
    (("張三", "國家發展委員會"), {"company": "國家發展委員會"}),
    (("張三", "天下雜誌"), {"company": "天下雜誌"}),
    (("張三", "中央通訊社"), {"company": "中央通訊社"}),
    (("張三", "臺灣銀行"), {"company": "臺灣銀行"}),
    (("張三", "臺北市政府"), {"company": "臺北市政府"}),
    (("張三", "建國高中"), {"company": "建國高中"}),
    (("Taipei City Government",), {"company_en": "Taipei City Government"}),
    # 弱關鍵字：沒有更強的候選時才當公司
    (("張三", "三立影音"), {"company": "三立影音"}),
    (("張三", "鏡新聞媒體"), {"company": "鏡新聞媒體"}),
    (("張三", "工研院產業科技國際策略發展中心"), {"company": "工研院產業科技國際策略發展中心"}),
    # 弱關鍵字遇到強關鍵字 → 弱的當部門
    (("張三", "研發中心", "光躍科技股份有限公司"), {"company": "光躍科技股份有限公司", "department": "研發中心"}),
    # 以 部/處/課/組/室 結尾的是部門，不是公司
    (("陳一", "國際業務部 經理", "測試股份有限公司"),
     {"company": "測試股份有限公司", "department": "國際業務部", "title": "經理"}),
    (("陳一", "數位媒體部", "某某有限公司"), {"company": "某某有限公司", "department": "數位媒體部"}),
    # 公司 + 標語同一行
    (("大麥網路股份有限公司 國發基金投資公司 | 創櫃板股票代號7600",),
     {"company": "大麥網路股份有限公司"}),
]


@pytest.mark.parametrize("texts,expected", CASES, ids=[c[0][-1] if len(c[0]) else "" for c in CASES])
def test_company(texts, expected):
    d = parse_card(lines(*texts))
    assert pick(d, *expected) == expected


def sized(*rows):
    """(文字, 字高) → 一行一行。"""
    out, y = [], 0
    for t, h in rows:
        out.append({"text": t, "box": [[0, y], [300, y], [300, y + h], [0, y + h]]})
        y += h + 10
    return out


def test_university_beats_institute_by_size():
    d = parse_card(sized(("陳美玲 教授兼系主任", 83), ("教育學系", 53), ("教育政策與行政研究所", 51),
                         ("課程與教學研究所", 50), ("國立臺灣師範大學 NTNU", 203)))
    assert pick(d, "name", "company", "department") == {
        "name": "陳美玲", "company": "國立臺灣師範大學", "department": "教育學系"}


def test_government_unit_and_split_english():
    d = parse_card(sized(("DEPARTMENT", 125), ("FOR YOUTH", 128), ("臺北市政府", 377), ("青年局", 433),
                         ("TAIPEI CITY", 139), ("GOVERNMENT", 143)))
    assert pick(d, "company", "company_en") == {"company": "臺北市政府青年局", "company_en": "DEPARTMENT FOR YOUTH TAIPEI CITY GOVERNMENT"}


def test_section_chief():
    d = parse_card(sized(("國際發展科 股長", 85), ("Subdivision Chief", 69), ("陳雅婷", 139)))
    assert pick(d, "name", "department", "title", "company") == {
        "name": "陳雅婷", "department": "國際發展科", "title": "股長", "company": ""}


def test_english_name_and_title_same_line():
    d = parse_card(lines("Mei-Ling Chen Professor and Chair", "Graduate Institute of Educational Policy and",
                         "Administration", "NATIONAL TAIWAN NORMAL UNIVERSITY"))
    assert pick(d, "name_en", "title_en", "company_en") == {
        "name_en": "Mei-Ling Chen", "title_en": "Professor and Chair",
        "company_en": "NATIONAL TAIWAN NORMAL UNIVERSITY"}


@pytest.mark.parametrize("email,expected", [
    ("yuenfoong@yfp.com.tw", "Yfp"), ("a@ntnu.edu.tw", ""), ("ab1234@gov.taipei", ""),
    ("x@gmail.com", ""), ("x@mail.acme.com", "Acme"),
])
def test_guess_company_from_email(email, expected):
    assert parse_card(lines("王小明", email))["company_en"] == expected


@pytest.mark.parametrize("title", ["Senior Product Manager", "Vice President Sales", "Global Account Director",
                                   "Managing Director", "Chief Technology Officer"])
def test_pure_english_title_not_split(title):
    d = parse_card(lines("王小明", title))
    assert pick(d, "name_en", "title_en") == {"name_en": "", "title_en": title}


def test_affiliation_line_not_split_as_department():
    d = parse_card(lines("莊雅琪", "委員", "國立雲林科技大學博士生", "台南柚城藝術家協會常務理事"))
    assert pick(d, "title", "department") == {"title": "委員", "department": ""}
    assert "國立雲林科技大學博士生" in d["other"] and "台南柚城藝術家協會常務理事" in d["other"]


def test_multiline_address_and_roc_typo():
    d = parse_card(lines("100025臺北市中正區", "仁爱路一段17號", "209 Songjiang Road", "Taipei, Taiwan 104472, R.0.C."))
    assert d["address"] == "100025臺北市中正區仁愛路一段17號"
    assert d["address_en"] == "209 Songjiang Road, Taipei, Taiwan 104472, R.O.C."


def test_logo_side_uploaded_as_front():
    from app.pipeline import merge_cards
    logo = lines("DEPARTMENT", "FOR YOUTH", "臺北市政府", "青年局", "TAIPEI CITY", "GOVERNMENT")
    person = lines("陳雅婷", "Ivy CHEN", "ab1234@gov.taipei")
    d = merge_cards(logo, person)
    assert pick(d, "name", "name_en") == {"name": "陳雅婷", "name_en": "Ivy CHEN"}


@pytest.mark.parametrize("text", ["FOR YOUTH", "TAIPEI CITY", "Thank You", "Taipei Office"])
def test_not_english_name(text):
    assert parse_card(lines("王小明", text))["name_en"] == ""


# ---- 第二批名片（使用者 2026-10-20 提供）的版面 ----
def test_spaced_address_and_separate_ext():
    d = parse_card(sized(("黃國華", 60), ("影響力事業部", 25), ("總監兼 CSR 頻道總編輯", 25), ("0912-345-678", 30),
                         ("天下雜誌", 35), ("台北市 104 南京東路二段 139 號 11 樓", 28),
                         ("電話:(02) 2345-6789   分機:1234", 28), ("傳真:(02) 2345-6790", 28),
                         ("統一編號:22039731", 28), ("電子信箱:peter.huang@example.com.tw", 28), ("網址:www.cw.com.tw", 28)))
    assert pick(d, "name", "company", "department", "title", "address", "tax_id") == {
        "name": "黃國華", "company": "天下雜誌", "department": "影響力事業部", "title": "總監兼 CSR 頻道總編輯",
        "address": "台北市104南京東路二段139號11樓", "tax_id": "22039731"}
    assert [phone_key(x) for x in d["phone"]] == ["0223456789#1234"]
    assert [phone_key(x) for x in d["mobile"]] == ["0912345678"]


def test_886_area_code_in_parens():
    d = parse_card(lines("Peter Huang", "Tel: (886-2)2345-6789", "Ext: 1234", "Fax: (886-2)2345-6790",
                         "Mobile: (886)912-345678", "E-mail: peter.huang@example.com.tw"))
    assert [phone_key(x) for x in d["phone"]] == ["0223456789#1234"]
    assert [phone_key(x) for x in d["fax"]] == ["0223456790"]
    assert [phone_key(x) for x in d["mobile"]] == ["0912345678"]


def test_tax_id_with_hyphen():
    assert parse_card(lines("宋怡君", "統編 1234-5678"))["tax_id"] == "12345678"


def test_english_name_with_initials():
    d = parse_card(sized(("Senior Executive Officer", 30), ("Annie M.Y. Wu", 50)))
    assert pick(d, "name_en", "title_en") == {"name_en": "Annie M.Y. Wu", "title_en": "Senior Executive Officer"}


def test_multiline_english_org():
    d = parse_card(sized(("桃園市政府", 40), ("智慧城鄉發展委員會", 40), ("Taoyuan City Government", 22),
                         ("Smart City and Community", 22), ("Development Commission", 22), ("T 03-1234567#100", 25)))
    assert pick(d, "company", "company_en") == {
        "company": "桃園市政府智慧城鄉發展委員會",
        "company_en": "Taoyuan City Government Smart City and Community Development Commission"}


def test_title_continued_with_ji():
    d = parse_card(lines("Co-Founder&COO", "共同創辦人暨", "營運總監", "林雅雯"))
    assert d["title"] == "共同創辦人暨營運總監"


def test_vertical_lawyer_card():
    d = parse_card(lines("構思法律事務所", "陳志明律師", "零貳 貳參肆伍 陸柒捌玖", "MAIL@EXAMPLELAW.NET",
                         "WWW.EXAMPLELAW.NET", "新竹縣竹北市自強七街三十三號五樓"))
    assert pick(d, "name", "title", "company", "address") == {
        "name": "陳志明", "title": "律師", "company": "構思法律事務所", "address": "新竹縣竹北市自強七街三十三號五樓"}
    assert [phone_key(x) for x in d["phone"]] == ["0223456789"]


def test_company_without_legal_suffix():
    d = parse_card(sized(("塗志偉", 45), ("Jason", 30), ("CEO", 30), ("0911-222-333", 30),
                         ("zhiwei@example.com", 30), ("和氏科技", 30)))
    assert pick(d, "name", "name_en", "title_en", "company") == {
        "name": "塗志偉", "name_en": "Jason", "title_en": "CEO", "company": "和氏科技"}


# ---- 2026-10-20 逐張檢查修正的情況 ----
def test_name_left_column_url_right_column():
    d = parse_card(lines("林建宏 www.cathayholdings.com", "陳淑芬 11493台北市內湖區堤頂大道二段295號9樓"))
    assert d["name"] in ("林建宏", "陳淑芬") and d["website"] == ["www.cathayholdings.com"]
    assert d["address"] == "11493台北市內湖區堤頂大道二段295號9樓"


def test_tax_id_not_phone():
    d = parse_card(lines("董事長特助暨代理發言人 統編：87654321"))
    assert d["tax_id"] == "87654321" and d["phone"] == [] and d["title"] == "董事長特助暨代理發言人"


def test_brand_vs_legal_name_and_university_dept():
    d = parse_card(sized(("國泰金控", 120), ("國泰金融控股股份有限公司", 110)))
    assert d["company"] == "國泰金融控股股份有限公司"
    d = parse_card(sized(("中央警察大學", 40), ("犯罪防治學系研究所", 38), ("張家豪 博士生", 60)))
    assert pick(d, "company", "department", "name") == {
        "company": "中央警察大學", "department": "犯罪防治學系研究所", "name": "張家豪"}
    d = parse_card(sized(("構思法律事務所", 40), ("政治大學財經法學博士班", 40), ("陳志明 律師", 60)))
    assert d["company"] == "構思法律事務所"


def test_logo_word_not_name():
    d = parse_card(sized(("天下", 150), ("黃國華", 119), ("雜誌", 67), ("天下雜誌", 81)))
    assert pick(d, "name", "company") == {"name": "黃國華", "company": "天下雜誌"}


def test_zh_side_and_en_side_merge():
    from app.pipeline import merge_cards
    zh = sized(("黃國華", 119), ("影響力事業部", 56), ("天下雜誌", 81), ("0912-345-678", 48))
    en = sized(("康健", 123), ("Peter Huang", 111), ("CommonWealth Magazine", 100), ("Mobile: (886)912-345678", 64),
               ("E-mail: peter.huang@example.com.tw", 64))
    d = merge_cards(zh, en)
    assert pick(d, "name", "name_en", "company", "company_en") == {
        "name": "黃國華", "name_en": "Peter Huang", "company": "天下雜誌", "company_en": "CommonWealth Magazine"}


def test_ocr_glitch_rules():
    from app.parser import _fix_admin_names, normalize
    assert _fix_admin_names("桃国市绝山區大岡里樹人路56號") == "桃園市龜山區大岡里樹人路56號"
    assert _fix_admin_names("台北市大安區仁愛路") == "台北市大安區仁愛路"  # 台/臺 都合法，不動
    assert normalize("BIOTECHNOLOGYCO, LTD.") == "BIOTECHNOLOGY CO., LTD."
    assert normalize("YOUTHCOMMISSIONER") == "YOUTH COMMISSIONER"
    assert normalize("E|M|AIT") == "EMAT"
    d = parse_card(lines("YOUTH COMMISSIONER KCG", "ATTORNEY AT LAW"))
    assert d["title_en"] == "YOUTH COMMISSIONER" and "KCG" in d["other"]
    assert parse_card(lines("ATTORNEY AT LAW"))["title_en"] == "ATTORNEY AT LAW"
    d = parse_card(sized(("EMAT", 60), ("擴益媒體", 70)))
    assert pick(d, "company", "company_en") == {"company": "擴益媒體", "company_en": "EMAT"}


# ---- 整頁拍照（4×2）----
def test_sheet_pairing_and_mirror():
    from app.sheet import pair_sheets
    fronts = [(c, f"F{c}", 3) for c in "ABCDEFGH"]
    backs = [(c, f"B{c}", 3) for c in "ABCDEFGH"]
    assert [(l, f, b) for l, f, b in pair_sheets(fronts, backs)][:2] == [("A", "FA", "BA"), ("B", "FB", "BB")]
    mir = {l: b for l, f, b in pair_sheets(fronts, backs, cols=2, mirror=True)}
    assert mir["A"] == "BB" and mir["B"] == "BA" and mir["G"] == "BH"   # 翻面時左右對調
    fronts[3], backs[3] = ("D", "FD", 0), ("D", "BD", 0)                 # D 位置兩面都沒字 → 空位
    assert "D" not in [l for l, f, b in pair_sheets(fronts, backs)]
    fronts[0] = ("A", "FA", 0)                                           # 正面只有 logo、反面有字 → 保留
    assert ("A", "FA", "BA") in pair_sheets(fronts, backs)


def test_sheet_cut_avoids_text():
    from app.sheet import _best_cut
    spans = [(0, 480, 20), (520, 1000, 20)]          # 左右兩張名片，中間 480~520 是空隙
    assert 480 < _best_cut(spans, 300, 700, 500, 1000) < 520
    spans = [(0, 560, 20), (600, 1000, 20)]           # 名片沒擺正：空隙偏右
    assert 560 < _best_cut(spans, 300, 700, 500, 1000) < 600


# ---- 標籤（自由索引）----
def test_normalize_tags():
    from app.db import normalize_tags, tag_list
    assert normalize_tags(["金融業，客戶、台北"]) == "金融業，客戶、台北"     # 輸入的整串就是一個標籤，不自動拆開
    assert normalize_tags(["A,B"]) == "A，B"                                 # 半形逗號（儲存分隔）轉全形
    assert normalize_tags(["金融業", " 餐廳 ", "金融業", " "]) == "金融業,餐廳"  # 去空白、去重
    assert normalize_tags("金融業,餐廳") == "金融業,餐廳"                      # 資料庫格式
    assert tag_list("金融業,餐廳") == ["金融業", "餐廳"] and tag_list("") == []
