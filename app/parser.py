"""規則式名片欄位解析：把 OCR 文字行轉成結構化欄位（不使用任何 LLM）。"""
import re
import unicodedata

# ---------- 字典 ----------
# 公司關鍵字分強弱：強 = 出現就算組織名；弱 = 常見於部門名（研發中心、數位媒體部），
# 只有整張名片找不到強關鍵字時才拿來當公司。英文一律「整字、不分大小寫」比對，關鍵字請寫小寫。
COMPANY_STRONG = [
    "股份有限公司", "有限公司", "公司", "集團", "金控", "銀行", "委員會", "雜誌", "通訊社", "企業社",
    "事務所", "工作室", "協會", "基金會", "醫院", "診所", "大學", "學院", "研究院", "研究所", "實業", "商行",
    "市政府", "政府", "高中", "辦事處", "代表處", "辦公室",
    "co.", "ltd", "inc", "corp", "corporation", "llc", "limited", "gmbh", "plc", "pte", "s.a.", "company",
    "bank", "university", "holdings", "labs", "technologies", "foundation", "association",
    "committee", "commission", "magazine", "news agency", "government", "school", "law firm", "firm",
    "trade office", "british office", "representative office", "economic and cultural office",
]
COMPANY_WEAK = [
    "中心", "媒體", "影音", "國際", "工業", "科技", "資訊", "設計", "顧問",
    "group", "technology", "tech", "techs", "studio", "media", "center", "centre", "institute", "international",
]
# 法定後綴：一行同時含職稱字眼時，必須有這些才算公司（避免 "Bank Manager"、"Group Leader"）
COMPANY_LEGAL = ["股份有限公司", "有限公司", "公司", "co.", "ltd", "inc", "corp", "corporation", "llc",
                 "limited", "gmbh", "plc", "pte", "s.a."]
DEPT_END_RE = re.compile(r"(?:部|處|課|組|室|科|股|學系|事業群|事業部)$")
# 接在組織名下一行、要併進公司名的單位：臺北市政府 + 青年局、臺灣銀行 + 信義分行
ORG_UNIT_RE = re.compile(r"^[\u4e00-\u9fff]{1,8}(?:局|署|分局|分署|分行|分公司|分院|分校)$")
TITLE_KW = [
    "董事長", "副董事長", "總經理", "副總經理", "執行長", "營運長", "財務長", "技術長", "總裁", "副總裁",
    "創辦人", "負責人", "合夥人", "協理", "經理", "副理", "副總", "資深", "主管", "襄理", "主任", "組長", "課長", "處長", "部長",
    "院長", "所長", "總監", "總編輯", "主編", "特助", "助理", "秘書", "專員", "工程師", "設計師", "顧問",
    "律師", "會計師", "建築師", "醫師", "教授", "研究員", "業務代表", "業務", "代表", "店長", "董事", "監事",
    "ceo", "cto", "coo", "cfo", "cmo", "vp", "svp", "evp", "president", "founder", "co-founder", "partner",
    "director", "manager", "engineer", "designer", "consultant", "specialist", "officer", "head of",
    "lead", "assistant", "associate", "analyst", "architect", "developer", "representative", "executive",
    "advisor", "professor", "researcher", "attorney", "lawyer", "owner", "chairman", "sales", "intern",
    "leader", "head", "chief", "supervisor", "coordinator", "secretary", "editor", "reporter", "journalist",
    "producer", "anchor", "commissioner", "記者", "編輯", "製作人", "主播", "委員",
    "股長", "科長", "局長", "副局長", "署長", "司長", "主任秘書", "專門委員", "技正", "技士", "科員", "辦事員",
    "系主任", "講師", "校長", "理事", "理事長", "常務理事", "監事", "主理人", "博士生", "研究生", "staff",
    "spokesperson", "deputy", "student", "phd", "secretary", "發言人",
]
DEPT_RE = re.compile(r"^([^\s]{1,12}?(?:部|處|課|組|室|科|學系|中心|事業群|事業部))(?=\s*\S)")
DEPT_EN_KW = ["department", "dept", "division"]
DEPT_EN_WORDS = ["department", "dept", "division", "center", "centre", "office", "team", "unit", "section", "group"]
# 不會出現在人名裡的英文字（避免 "FOR YOUTH"、"TAIPEI CITY"、"Thank You" 被當英文名）
EN_NOT_NAME = {
    "for", "the", "of", "and", "to", "in", "at", "by", "with", "on", "from", "you", "your", "our", "we",
    "thank", "thanks", "welcome", "hello", "department", "city", "county", "government", "youth", "young",
    "office", "branch", "center", "centre", "road", "street", "national", "university", "college", "school",
    "taiwan", "taipei", "kaohsiung", "taichung", "tainan", "yunlin", "hsinchu", "news", "agency", "temple",
    "business", "card", "service", "services", "sales", "marketing", "team", "group", "international",
    "temsilci", "iroda", "irodavezető", "cabinet", "rector's", "office", "building", "stipendium", "hungaricum",
}
# 常放在職稱前面的修飾字：含這些字的片語不會被當成英文姓名（Senior Product Manager）
TITLE_MOD = ["senior", "sr", "junior", "jr", "product", "project", "program", "marketing", "business", "general",
             "technical", "regional", "global", "account", "software", "hardware", "data", "research", "customer",
             "finance", "financial", "human", "operations", "deputy", "principal", "staff", "vice", "managing",
             "creative", "art", "brand", "digital", "content", "chief", "assistant", "associate", "executive",
             "international", "country", "area", "district", "store", "branch", "office", "it", "hr", "pr"]

LABELS = {
    "mobile": r"(?:手機|行動電話|行動|mobile|mob|cell|cellphone|m)",
    "phone": r"(?:電話|市話|總機|專線|tel|telephone|phone|office|direct|t|p|o)",
    "fax": r"(?:傳真|fax|f)",
    "email": r"(?:e-?mail|電子郵件|郵件|信箱|mail|e)",
    "website": r"(?:網址|網站|官網|web|website|url|w)",
    "address": r"(?:地址|住址|通訊處|address|addr|add|a)",
    "tax_id": r"(?:統一編號|統編|tax\s*id|vat)",
    "line_id": r"(?:line\s*id|line)",
    "wechat": r"(?:wechat|微信)",
}
# 單一字母標籤後面必須接空白、冒號或「+/(/數字」才算，避免把 "Emily" 當成 E 標籤
LABEL_RE = {
    k: re.compile(rf"^\s*{v}(?:\s*[:：]\s*|\s+|(?=[+(\d]))", re.I) for k, v in LABELS.items()
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)[^\s，,;]+|https?://[^\s，,;]+|"
    r"\b[a-z0-9\-]+(?:\.[a-z0-9\-]+)*\.(?:com|net|org|io|co|tw|cn|jp|hk|sg|ai|app|dev)(?:\.[a-z]{2})?(?:/[^\s]*)?\b",
    re.I,
)
PHONE_RE = re.compile(
    r"(?<![A-Za-z@\d])(?:\+?\d{1,3}[\s\-.]?)?(?:\(\+?\d{1,4}(?:-\d{1,4})?\)\s*)?\d[\d\s\-.]{5,}\d(?![A-Za-z@])"
    r"(?:\s*(?:#|ext\.?|分機|轉|x)\s*[:：]?\s*\d{1,6})?",
    re.I,
)
TW_MOBILE_RE = re.compile(r"^(?:\+?886[\s\-]?9|09)\d")
EXT_ONLY_RE = re.compile(r"^(?:ext\.?|分機|轉)\s*[:：]?\s*(\d{1,6})$", re.I)
CN_DIGITS = str.maketrans("零〇壹貳參叁肆伍陸柒捌玖", "001233456789")
TAX_ID_RE = re.compile(r"\b\d{8}\b")
ZH_ADDR_RE = re.compile(r"(?:\d{3,6})?\S{0,6}?(?:市|縣|省)\S*?(?:區|鄉|鎮|市|路|街|道)\S*?(?:號|樓|室|F)", re.I)
ZH_ADDR_START_RE = re.compile(r"^\d{3,6}?\s*[\u4e00-\u9fff]{0,4}(?:市|縣)[\u4e00-\u9fff]{1,4}(?:區|鄉|鎮|市)$")
ZH_ADDR_CONT_RE = re.compile(r"[\u4e00-\u9fff0-9]+(?:路|街|大道|段|巷|弄|號|樓|室|F)", re.I)
EN_ADDR_CONT_RE = re.compile(
    r"\b(?:Dist\.?|District|City|County|Township|Taiwan|R\.?\s?[O0]\.?\s?C\.?|Taipei|New Taipei|Kaohsiung|Taichung|"
    r"Tainan|Taoyuan|Hsinchu|USA|Japan|China|Hong Kong|Singapore|Road|Rd\.?|Sec\.?|Floor|\d+F)\b|\b\d{5,6}\b", re.I)
# PP-OCR 偶爾把繁體地址字認成簡體
ADDR_ZH_FIX = str.maketrans("爱区号楼东门圣丰兴广华乡镇县湾", "愛區號樓東門聖豐興廣華鄉鎮縣灣")
# 台灣名片：PP-OCR 偶爾把繁體字認成簡體，常見的幾個字直接轉回來
OCR_ZH_FIX = str.maketrans("学国爱区号楼内统编话务发会业电机银处经济师传真码钟积际门东长续虚长场传设计视关划",
                           "學國愛區號樓內統編話務發會業電機銀處經濟師傳真碼鐘積際門東長續處長場傳設計視關劃")
EN_ADDR_RE = re.compile(
    r"\d+\s+[\w .]+\b(?:st|street|ave|avenue|rd|road|blvd|boulevard|lane|ln|dr|drive|way|suite|ste|floor|fl)\b",
    re.I,
)
# 台灣式英文地址：No.99, Sec. 3, Taiwan Blvd., Xitun Dist., Taichung
TW_EN_ADDR_RE = re.compile(
    r"\b(?:No\.|Sec\.|Rd\.|Road|St\.|Blvd\.|Ave\.|Dist\.|District|Ln\.|Lane|Aly\.|Alley|Village|Township|City|County)"
    r"|\b\d+F\b|\bFl\.", re.I)
CJK = r"一-鿿㐀-䶿"
ZH_NAME_RE = re.compile(rf"^[{CJK}]{{2,4}}$")
EN_NAME_RE = re.compile(r"^[A-ZÀ-ÖØ-ÞĀ-Ž][A-Za-zÀ-ÖØ-öø-ÿĀ-ž'\-]+(?:\s+(?:[A-Z]\.){1,3}|\s+[A-Z]\.?)?(?:\s+[A-ZÀ-ÖØ-ÞĀ-Ž][A-Za-zÀ-ÖØ-öø-ÿĀ-ž'\-]+){1,2}$")  # 含歐洲重音字母（Müller、ÁRPÁD）
MIXED_NAME_RE = re.compile(rf"^(?P<en>[A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+)?)\s+(?P<zh>[{CJK}](?:\s?[{CJK}]){{1,3}})$")
MIXED_NAME_RE2 = re.compile(rf"^(?P<zh>[{CJK}](?:\s?[{CJK}]){{1,3}})\s+(?P<en>[A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+)?)$")
COMMON_SURNAMES = set(
    "王李張劉陳楊黃趙吳周徐孫馬朱胡郭何高林羅鄭梁謝宋唐許韓馮鄧曹彭曾蕭田董袁潘于蔣蔡余杜葉程蘇魏呂丁任沈"
    "姚盧姜崔鍾譚陸汪范金石廖賈夏韋付方白鄒孟熊秦邱江尹薛閻段雷侯龍史陶黎賀顧毛郝龔邵萬錢嚴覃武戴莫孔向湯"
    "游詹賴洪柯翁童傅施莊溫藍歐簡紀卓巫涂鄔辜連古康白麥"
)


# ---------- 地址校正 ----------
def _fix_admin_names(addr: str) -> str:
    """縣市、鄉鎮市區名和真實名稱只差一個字時校正（OCR 把金箔字認錯：桃国市绝山區 → 桃園市龜山區）。"""
    from .tw_admin import CITIES, DISTRICT_NAMES

    def close(a, b):
        return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) <= 1

    m = re.search(r"([\u4e00-\u9fff]{2})(市|縣)", addr)
    if not m:
        return addr
    raw_city = m.group(1).replace("台", "臺") + m.group(2)
    city = next((c for c in CITIES if c == raw_city), None) or next((c for c in CITIES if close(c, raw_city)), None)
    if not city:
        return addr
    if raw_city != city and m.group(1)[0] != "台":
        addr = addr[:m.start()] + city + addr[m.end():]
    rest_at = m.start() + 3
    m2 = re.match(r"([\u4e00-\u9fff]{1,3}?)(區|鄉|鎮|市)", addr[rest_at:])
    if m2:
        d = m2.group(1)
        names = DISTRICT_NAMES[city]
        if d not in names:
            fix = [n for n in names if close(n, d)]
            if len(fix) == 1:
                addr = addr[:rest_at] + fix[0] + addr[rest_at + len(d):]
    return addr


# ---------- 工具 ----------
def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)  # 全形 → 半形
    s = s.replace("{", "(").replace("}", ")").replace("［", "[").replace("］", "]")
    s = re.sub(r"\s+", " ", s).strip()
    s = s.translate(OCR_ZH_FIX)
    # email 常見 OCR 誤認：gmaiLcom / gmail,com → gmail.com
    s = re.sub(r"@gmai[lL1I][.,]?com\b", "@gmail.com", s)
    s = re.sub(r"\bR\.\s?[0O]\.\s?C\.?", "R.O.C.", s)  # R.0.C.
    s = re.sub(r"\bTa[l1I]wan\b", "Taiwan", s)              # Talwan
    s = re.sub(r"\bNo\.\s?[Il](?=\d)", "No.1", s)            # No.I7 → No.17
    # 公司後綴黏到前一個字：BIOTECHNOLOGYCO, LTD. → BIOTECHNOLOGY CO., LTD.
    s = re.sub(r"([A-Za-z]{3})(CO|Co)\s*[.,]\s*,?\s*(LTD|Ltd)\b", r"\1 \2., \3", s)
    # 全大寫職稱黏在一起：YOUTHCOMMISSIONER → YOUTH COMMISSIONER
    if s.isupper():
        def _split(tok):
            for kw in ("COMMISSIONER", "CONSULTANT", "DIRECTOR", "MANAGER", "ENGINEER", "OFFICER", "PRESIDENT", "SECRETARY"):
                if tok.endswith(kw) and len(tok) > len(kw) + 2 and tok[:-len(kw)].isalpha():
                    return tok[:-len(kw)] + " " + kw
            return tok
        s = " ".join(_split(t) for t in s.split(" "))
    # 字母間隔 logo：E|M|AIT、E·M·A·T → EMAT（夾在中間的 I/l 多半是分隔線被認成字母）
    if re.fullmatch(r"(?:[A-Z][|·•\s]+){2,}[A-Z][A-Z|Il]*", s.strip()):
        parts = [x for x in re.split(r"[|·•\s]+", s.strip()) if x]
        if all(len(x) == 1 for x in parts[:-1]) and len(parts[-1]) > 1:
            parts = parts[:-1] + [c for c in re.split(r"[Il]", parts[-1]) if c]
        s = "".join(parts)
    s = re.sub(r"(?<=\d)[Il](?=\d)", "1", s)
    # 左側 logo 字和英文同一列：「天下 Director & Managing Editor」→ 去掉非姓氏開頭的中文前綴
    m = re.match(r"^([\u4e00-\u9fff]{1,4})\s+(?=[A-Za-z(])(.*)$", s)
    if m and m.group(1)[0] not in COMMON_SURNAMES and len(re.findall(r"[A-Za-z]{2,}", m.group(2))) >= 2:
        s = m.group(2)
    if re.fullmatch(r"[零〇壹貳參叁肆伍陸柒捌玖\s\-]{6,}", s):  # 「零貳 貳參肆伍 陸柒捌玖」大寫數字電話
        s = s.translate(CN_DIGITS)
    s = re.sub(r"(@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*),(com|net|org|tw)\b", r"\1.\2", s)
    # 圖示（📍☎✏️）常被 OCR 成開頭的雜符號
    return re.sub(r"^[^\w\u4e00-\u9fff+(]+|[\s|/\\·•,]+$", "", s).strip()


def clean_phone(s: str) -> str:
    s = s.strip(" .-")
    s = re.sub(r"\s*(?:#|ext\.?|分機|轉|x)\s*[:：]?\s*(\d+)$", r" #\1", s, flags=re.I)
    return re.sub(r"\s{2,}", " ", s)


_KW_RE_CACHE = {}


def _kw_re(k: str):
    """英文關鍵字：整字比對（前後不能接英文字母），中文：子字串比對。都不分大小寫。"""
    k = k.lower()
    if k not in _KW_RE_CACHE:
        if re.search(r"[a-z]", k) and len(k) >= 10:  # 長字允許前面黏字：OCR 漏空白的 YOUTHCOMMISSIONER
            _KW_RE_CACHE[k] = re.compile(rf"{re.escape(k)}(?![a-z])")
        elif re.search(r"[a-z]", k):
            _KW_RE_CACHE[k] = re.compile(rf"(?<![a-z]){re.escape(k)}(?![a-z])")
        else:
            _KW_RE_CACHE[k] = re.compile(re.escape(k))
    return _KW_RE_CACHE[k]


def phone_key(num: str) -> str:
    """電話正規化成可比對的 key：+886-2-1234-5678、(02)1234-5678 → 0212345678；分機保留成 #786。"""
    main, _, ext = re.sub(r"\s*(?:#|ext\.?|分機|轉|x)\s*[:：]?\s*", "#", num, count=1, flags=re.I).partition("#")
    d = re.sub(r"\D", "", main)
    if d.startswith("886"):
        d = "0" + d[3:].lstrip("0")
    ext = re.sub(r"\D", "", ext)
    return d + (f"#{ext}" if ext else "")


def has_kw(text: str, kws) -> bool:
    t = text.lower()
    return any(_kw_re(k).search(t) for k in kws)


def company_strength(text: str) -> int:
    """0 = 不是公司，1 = 弱（可能是部門），2 = 強。"""
    first = text.split(" ")[0]
    if text.strip().lower().rstrip(".") in COMPANY_STRONG + COMPANY_WEAK:  # 「雜誌」「Magazine」只是 logo 的一部分
        return 1
    strong, legal = has_kw(text, COMPANY_STRONG), has_kw(text, COMPANY_LEGAL)
    if DEPT_END_RE.search(first) and not legal and not re.search(r"(?:辦事處|代表處)$", first):  # 「國際業務部」是部門
        return 0
    no_org = text.lower()
    for k in COMPANY_STRONG + COMPANY_WEAK:  # 先拿掉組織字眼，避免「委員會」裡的「委員」被當職稱
        no_org = _kw_re(k).sub(" ", no_org)
    if has_kw(no_org, TITLE_KW) and not legal:    # 「Group Leader」「Bank Manager」是職稱
        return 0
    if strong:
        return 2
    return 1 if has_kw(text, COMPANY_WEAK) else 0


def _company_name(text: str) -> tuple:
    """同一行有多段時（公司 + 標語），挑出公司那段；回傳 (公司名, 其餘文字)。"""
    if not re.search("[\u4e00-\u9fff]", text):
        return text, ""
    segs = [x for x in re.split(r"\s+|[|丨｜]", text) if x.strip()]
    if len(segs) < 2:
        return text, ""
    pick = ([x for x in segs if re.search(r"(股份)?有限公司$", x)] or
            [x for x in segs if company_strength(x) == 2] or [segs[0]])[0]
    return pick, " ".join(x for x in segs if x != pick)


def choose_company(items, out):
    """中、英文各挑一個公司：強 > 弱，同強度取最上面的一行。沒被選上的弱候選當部門。"""
    for is_zh, key in ((True, "company"), (False, "company_en")):
        cands = [(company_strength(i["text"]), n, i) for n, i in enumerate(items)
                 if not i["used"] and bool(re.search("[\u4e00-\u9fff]", i["text"])) == is_zh]
        cands = [c for c in cands if c[0] > 0]
        if not cands:
            continue
        # 強 > 弱；同強度挑字最大的（組織名通常印最大），再同就取最上面
        best = max(cands, key=lambda c: (c[0], has_kw(c[2]["text"], COMPANY_LEGAL), round(c[2]["h"] / 8), -c[1]))
        name, extra = _company_name(best[2]["text"])
        idx = items.index(best[2])
        best[2]["used"] = True
        if is_zh:
            name = _join_zh_org(items, idx, name)
        elif len(name.split()) <= 2 and name.isupper():
            name = _join_caps_org(items, idx, name)
        else:
            name = _join_en_org(items, idx, name)
        out[key] = name
        if extra:
            out["other"].append(extra)
        nxt = items[idx + 1] if idx + 1 < len(items) else None
        if is_zh and nxt and not nxt["used"] and not out["department"] and " " not in nxt["text"] \
                and re.search(r"(?:學系|研究所|學院|系|所|中心|處|部|室|科)$", nxt["text"]) \
                and not has_kw(nxt["text"], COMPANY_LEGAL + TITLE_KW):
            out["department"] = nxt["text"]
            nxt["used"] = True
        # 沒選上的弱候選（研發中心）：名片上沒有明確部門行時才當部門
        has_dept_line = any(not i["used"] and DEPT_END_RE.search(i["text"].split(" ")[0]) for i in items)
        for strength, _, it in cands:
            if strength == 1 and not it["used"] and is_zh and not out["department"] and not has_dept_line \
                    and it["text"].strip().lower() not in COMPANY_STRONG + COMPANY_WEAK:
                out["department"] = it["text"]
                it["used"] = True


def _similar_h(a, b, ratio=1.4):
    return max(a["h"], b["h"]) <= ratio * max(1, min(a["h"], b["h"]))


def _join_zh_org(items, idx, name):
    """上級機關 + 單位分兩行：雲林縣政府 / 第三屆青年事務諮詢委員會、臺北市政府 / 青年局。"""
    cur = items[idx]
    gov = lambda t: re.search(r"(?:政府|市|縣)$", t)
    prv = items[idx - 1] if idx > 0 else None
    if prv and not prv["used"] and gov(prv["text"]) and company_strength(prv["text"]) == 2 and _similar_h(prv, cur):
        name = prv["text"] + name                     # 雲林縣政府 + 第三屆青年事務諮詢委員會
        prv["used"] = True
    nxt = items[idx + 1] if idx + 1 < len(items) else None
    if nxt and not nxt["used"] and re.search("[\u4e00-\u9fff]", nxt["text"]) and " " not in nxt["text"] and (
            ORG_UNIT_RE.match(nxt["text"]) or (gov(name) and company_strength(nxt["text"]) == 2 and _similar_h(nxt, cur))):
        name += nxt["text"]                           # 臺北市政府 + 青年局；桃園市政府 + 智慧城鄉發展委員會
        nxt["used"] = True
    return name


def _join_caps_org(items, idx, name):
    """全大寫英文機關名拆成多行（中間可能夾直排中文）：DEPARTMENT / FOR YOUTH / … / TAIPEI CITY / GOVERNMENT。"""
    j, n = idx - 1, 0
    while j >= 0 and n < 6 and len(name) < 80:
        t = items[j]["text"]
        if re.search("[\u4e00-\u9fff]", t):  # 跳過中間的中文行
            j -= 1
            continue
        if items[j]["used"] or not t.isupper() or re.search(r"[\d@]", t) or has_kw(t, TITLE_KW):
            break
        name = t + " " + name
        items[j]["used"] = True
        j, n = j - 1, n + 1
    return name


def _join_en_org(items, idx, name):
    """英文機關名換行：Taoyuan City Government / Smart City and Community / Development Commission。
    往下最多接 2 行字高相近、無數字/@ 的英文行，且接完的最後一行要含組織字（commission…）才算。"""
    block, j = [], idx + 1
    while j < len(items) and len(block) < 2:
        t = items[j]["text"]
        if items[j]["used"] or re.search(f"[{CJK}\\d@]", t) or not _similar_h(items[j], items[idx], 1.3) \
                or t.strip().lower() == name.strip().lower() \
                or has_kw(t, TITLE_KW):
            break
        block.append(items[j])
        j += 1
    while block and not has_kw(block[-1]["text"], COMPANY_STRONG + COMPANY_WEAK):
        block.pop()
    for b in block:
        name += " " + b["text"]
        b["used"] = True
    return name


def strip_label(text: str):
    for field, rx in LABEL_RE.items():
        m = rx.match(text)
        if m:
            return field, text[m.end():].strip()
    return None, text


LABEL_WORDS_RE = re.compile(
    r"(?:電話|傳真|手機|行動電話|行動|電郵|電子信箱|電子郵件|信箱|網址|網站|統一編號|統編|分機|地址|"
    r"\btel\b|\bfax\b|\bmobile\b|\bmob\b|e-?mail|\bwebsite\b|\bweb\b|\bext\b|\bline\b)\.?\s*[:：]?", re.I)


def _residual(t):
    """一列裡抽走 email / 網址 / 電話 / 標籤後剩下的文字（常是另一欄的姓名、部門）。"""
    r = EMAIL_RE.sub(" ", t)
    r = URL_RE.sub(" ", r)
    r = PHONE_RE.sub(" ", r)
    r = LABEL_WORDS_RE.sub(" ", r)
    r = re.sub(r"\s+", " ", re.sub(r"[|｜/,:：#]+", " ", r)).strip()
    return r if re.search(f"[{CJK}]{{2,}}|[A-Za-z]{{3,}}", r) else ""


def _uniq_append(lst, v):
    if v and v not in lst:
        lst.append(v)


# ---------- 主流程 ----------
def parse_card(lines, guess_company=True):
    """lines: list of dict(text, score, box[[x,y]*4])。回傳結構化 dict。"""
    out = {  # 依重要性排列：姓名 → 單位 → Email → 電話 → 職稱 / 部門 → 地址 → 其他
        "name": "", "name_en": "", "company": "", "company_en": "",
        "email": [], "mobile": [], "phone": [],
        "title": "", "title_en": "", "department": "", "department_en": "",
        "address": "", "address_en": "", "fax": [], "website": [], "tax_id": "", "line_id": "", "wechat": "",
        "other": [],
    }
    items = []
    for ln in lines:
        t = normalize(ln["text"])
        if not t:
            continue
        box = ln.get("box") or [[0, 0]] * 4
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append({"text": t, "h": max(ys) - min(ys), "y": min(ys), "x": min(xs), "used": False})

    # 1) 有明確格式/標籤的欄位
    for k, it in enumerate(items):
        if it["used"]:
            continue
        t = it["text"]
        label, rest = strip_label(t)

        for e in EMAIL_RE.findall(t):
            _uniq_append(out["email"], e.lower())
        t_no_mail = EMAIL_RE.sub(" ", t)

        m = re.search(r"(?:統一編號|統編|tax\s*id|vat)\s*[:：]?\s*(\d{4}-?\d{4})(?!\d)", t, re.I)
        if m:
            out["tax_id"] = m.group(1).replace("-", "")
            t = (t[:m.start()] + " " + t[m.end():]).strip()
            it["text"] = t
            if not t:
                it["used"] = True
                continue
            label, rest = strip_label(t)
            t_no_mail = EMAIL_RE.sub(" ", t)
        if label in ("line_id", "wechat") and rest:
            out[label] = rest
            it["used"] = True
            continue

        urls = [u for u in URL_RE.findall(t_no_mail) if not re.fullmatch(r"[\d.\-]+", u)]
        if urls:
            for u in urls:
                u = re.sub(r"^[A-Za-z](?=https?://)", "", u)  # "Whttps://" → "https://"
                _uniq_append(out["website"], u.rstrip("/."))
            it["used"] = True

        if out["email"] and EMAIL_RE.search(t):
            it["used"] = True
        if it["used"]:
            res = _residual(t)
            if res:
                items.insert(k + 1, {**it, "text": res, "used": False})

        # 地址（可能跨 2~3 行）
        addr = rest if label == "address" else t
        is_zh_line = bool(re.search(f"[{CJK}]", t))
        if is_zh_line:
            compact = re.sub(r"\s+", "", t)
            compact = re.sub(r"^(?:地址|住址|通訊處)[:：]?", "", compact)
            m_addr = ZH_ADDR_RE.search(compact)
            if m_addr and not PHONE_RE.search(t) and "@" not in t:
                t = addr = compact
                pre = compact[:m_addr.start()]
                if re.fullmatch(f"[{CJK}]{{2,4}}", pre) and not re.search(r"地址|住址", pre):  # 前面黏著姓名
                    items.insert(k + 1, {**it, "text": pre, "used": False})
                    t = addr = compact[m_addr.start():]
                elif re.match(r"^(?:地址|住址)", pre):
                    t = addr = compact[len(re.match(r"^(?:地址|住址)", pre).group(0)):]
        if is_zh_line and (label == "address" or ZH_ADDR_RE.search(t) or
                           (ZH_ADDR_START_RE.match(t) and _next_is(items, k, _is_zh_addr_cont))):
            it["used"] = True
            out["address"] = out["address"] or _fix_admin_names(_absorb(items, k, addr, _is_zh_addr_cont, "").translate(ADDR_ZH_FIX))
            continue
        if not is_zh_line and (label == "address" or EN_ADDR_RE.search(t) or len(TW_EN_ADDR_RE.findall(t)) >= 2) \
                and not PHONE_RE.fullmatch(t) and "@" not in t:
            m_nm = re.match(r"^([A-Z][a-z]+(?: [A-Z][a-zA-Z]+){1,2}) (?=\d|No\.)", addr)
            if m_nm and _en_name_ok(m_nm.group(1)) and not TW_EN_ADDR_RE.search(m_nm.group(1)):
                items.insert(k + 1, {**it, "text": m_nm.group(1), "used": False})
                addr = addr[m_nm.end():]
            it["used"] = True
            out["address_en"] = out["address_en"] or _absorb(items, k, addr, _is_en_addr_cont, " ")
            continue

        # 電話（一行可能有多組）
        if it["used"]:
            continue
        segs = re.split(r"\s{2,}|[|/｜]|(?=(?:手機|電話|傳真|tel|fax|mobile)\s*[:：])", t_no_mail, flags=re.I)
        found = False
        for seg in segs:
            seg = seg.strip()
            if not seg:
                continue
            lab, val = strip_label(seg)
            ext = EXT_ONLY_RE.match(seg)
            if ext:
                last = out["phone"] or out["mobile"]
                if last and "#" not in last[-1]:
                    last[-1] += f" #{ext.group(1)}"
                    found = True
                continue
            for m in PHONE_RE.finditer(val):
                num = clean_phone(m.group(0))
                num = re.sub(r"^[1-9](?=0[2-8]-\d{3,4}-?\d{3,4}$)", "", num)  # 電話圖示被認成數字
                digits = re.sub(r"\D", "", num.split("#")[0])
                if len(digits) < 7 or len(digits) > 15:
                    continue
                groups = re.findall(r"\d+", num.split("#")[0])
                if len(groups) >= 3 and all(len(g) <= 2 for g in groups):  # 尺規刻度等雜訊
                    continue
                if lab == "fax":
                    key = "fax"
                elif lab == "mobile" or TW_MOBILE_RE.match(num) or re.fullmatch(r"09\d{8}", phone_key(num)):
                    key = "mobile"
                else:
                    key = "phone"
                _uniq_append(out[key], num)
                found = True
        if found:
            it["used"] = True
            res = _residual(t_no_mail)
            if res:
                items.insert(k + 1, {**it, "text": res, "used": False})

    # 以上 1) 是「錨點欄位」：email / 網址 / 統編 / 地址 / 電話格式固定、幾乎不會認錯，
    # 先抽出來只是為了縮小候選範圍。接下來需要判斷的欄位，依重要性決定、重要的先挑：
    #   2) 姓名 → 3) 單位（公司） → 4) 職稱 / 部門
    rest_items = [i for i in items if not i["used"]]
    _pick_name(rest_items, items, out)
    choose_company(rest_items, out)
    _pick_title_dept(rest_items, out)

    if out["company"] and not out["company_en"]:
        for it in items:  # 中文公司名旁邊的 2~6 字母全大寫字 = 英文簡稱（EMAT 擴益媒體）
            if not it["used"] and re.fullmatch(r"[A-Z]{2,6}", it["text"]) and not has_kw(it["text"], TITLE_KW) \
                    and it["text"].lower() not in EN_NOT_NAME and any(
                        j["used"] and j["text"] == out["company"] and abs(j["y"] - it["y"]) < 3 * max(j["h"], it["h"])
                        for j in items):
                out["company_en"] = it["text"]
                it["used"] = True
                break
    for it in items:
        if not it["used"]:
            out["other"].append(it["text"])
    out["website"] = [w.lower() for w in out["website"] if not any(e.endswith("@" + w.lower()) for e in out["email"])]
    for k in ("address", "address_en"):  # OCR 多出來的逗號：「, ,Guishan」
        out[k] = re.sub(r"\s*,(?:\s*,)+\s*", ", ", out[k]).strip(" ,")
    if guess_company:
        guess_company_from_email(out)
    return out


def _pick_name(rest_items, items, out):
    """2) 姓名（最重要，第一個挑）。先看「姓名和職稱 / 英文名同一列」的寫法，再從剩下的行挑。
    候選要排除職稱、部門、組織字（它們還沒被挑走）。"""
    for it in rest_items:
        if it["used"]:
            continue
        t = it["text"]
        is_zh = bool(re.search(f"[{CJK}]", t))
        m = MIXED_NAME_RE.match(t) or MIXED_NAME_RE2.match(t)  # 「Tony 王 大明」
        if m and not has_kw(t, TITLE_KW) and not company_strength(t):
            out["name_en"] = out["name_en"] or m.group("en").strip()
            out["name"] = out["name"] or m.group("zh").replace(" ", "")
            it["used"] = True
            continue
        if not is_zh and not out["name_en"]:  # 「Mei-Ling Chen Professor and Chair」
            ws = t.split(" ")
            for n in (3, 2):
                head, tail = " ".join(ws[:n]), " ".join(ws[n:])
                if len(ws) > n and EN_NAME_RE.match(head) and not has_kw(head, TITLE_KW + TITLE_MOD + DEPT_EN_KW) \
                        and has_kw(ws[n], TITLE_KW + ["senior", "sr.", "junior", "jr.", "vice", "assistant", "associate"]):
                    out["name_en"] = head
                    _set_title(out, tail, False)
                    it["used"] = True
                    break
            if it["used"]:
                continue
        m2 = re.fullmatch(f"([{CJK}]{{2,4}}?)(律師|醫師|會計師|建築師|教授|老師|記者|委員|經理|主任)", t.replace(" ", ""))
        if is_zh and m2 and m2.group(1)[0] in COMMON_SURNAMES and not out["name"]:  # 「陳志明律師」
            out["name"] = m2.group(1)
            _add_title(out, "title", m2.group(2))
            it["used"] = True
            continue
        parts = t.split(" ")  # 「李美華 經理」
        if is_zh and len(parts) >= 2 and ZH_NAME_RE.match(parts[0]) and has_kw(" ".join(parts[1:]), TITLE_KW) \
                and parts[0][0] in COMMON_SURNAMES and not has_kw(parts[0], TITLE_KW) and not out["name"]:
            out["name"] = parts[0]
            _set_title(out, " ".join(parts[1:]), True)
            it["used"] = True

    cands = [i for i in rest_items if not i["used"]]
    for i in list(cands):  # 「天下 黃國華」：logo 和姓名同列 → 拆出姓名段
        toks = i["text"].split()
        if len(toks) >= 2 and re.search(f"[{CJK}]", i["text"]):
            nm = [x for x in toks if ZH_NAME_RE.match(x) and x[0] in COMMON_SURNAMES and not has_kw(x, TITLE_KW)]
            if len(nm) == 1:
                i["used"] = True
                cands.append({**i, "text": nm[0], "used": False})
                rest_t = " ".join(x for x in toks if x != nm[0])
                rest_items.append({**i, "text": rest_t, "used": False})
                items.append(rest_items[-1])

    def not_other_field(t):  # 不是職稱、組織、部門、機關單位（青年局、信義分行）
        c = t.replace(" ", "")
        return not has_kw(t, TITLE_KW) and not company_strength(t) and not DEPT_END_RE.search(c) \
            and not ORG_UNIT_RE.match(c)

    zh = [i for i in cands if not i["used"] and ZH_NAME_RE.match(i["text"].replace(" ", "")) and not_other_field(i["text"])]
    if zh and not out["name"]:
        best = max(zh, key=lambda i: (i["text"][0] in COMMON_SURNAMES, i["h"]))  # 常見姓氏優先，其次字最大
        out["name"] = best["text"].replace(" ", "")
        best["used"] = True
        if out["name"][0] not in COMMON_SURNAMES and len(out["name"]) == 2:  # 直排「林 / (阿y) / 育暄」
            sur = [i for i in cands if not i["used"] and len(i["text"]) == 1 and i["text"] in COMMON_SURNAMES]
            if sur:
                out["name"] = sur[0]["text"] + out["name"]
                sur[0]["used"] = True
    en_ok = lambda t: _en_name_ok(t) and not_other_field(t) and not has_kw(t, TITLE_MOD + DEPT_EN_WORDS)
    en = [i for i in cands if not i["used"] and EN_NAME_RE.match(i["text"]) and en_ok(i["text"])]
    if not en and not out["name_en"]:  # 只有英文名（Tony / Amy）
        en = [i for i in cands if not i["used"] and re.fullmatch(r"[A-Z][a-z]{2,15}", i["text"]) and en_ok(i["text"])]
    if en and not out["name_en"]:
        best = max(en, key=lambda i: (_email_hits(i["text"], out["email"]), i["h"]))  # email 帳號對得上的優先
        out["name_en"] = best["text"]
        best["used"] = True


def _pick_title_dept(rest_items, out):
    """4) 職稱 / 部門：姓名、單位都挑完後，剩下的行裡找。"""
    for it in rest_items:
        if it["used"]:
            continue
        t = it["text"]
        is_zh = bool(re.search(f"[{CJK}]", t))
        if is_zh and DEPT_END_RE.search(t) and " " not in t and not has_kw(t, TITLE_KW):  # 只有部門
            _add_dept(out, "department", t)
            it["used"] = True
        elif has_kw(t, TITLE_KW) or has_kw(t, DEPT_EN_KW):
            _set_title(out, t, is_zh)
            it["used"] = True


FREE_MAIL = {"gmail", "yahoo", "hotmail", "outlook", "icloud", "msn", "qq", "163", "126", "live", "me", "hinet",
             "seed", "pchome", "protonmail", "aol"}
GENERIC_DOMAIN = {"com", "net", "org", "edu", "gov", "co", "ac", "or", "go", "tw", "cn", "hk", "jp", "sg", "io", "mail"}


def guess_company_from_email(out):
    """完全沒抓到公司時，用 email 網域猜英文公司（正反面合併後再呼叫）。gov / edu / 免費信箱不猜。"""
    if out["company"] or out["company_en"] or not out["email"]:
        return out
    parts = out["email"][0].split("@")[1].lower().split(".")
    if FREE_MAIL & set(parts) or {"gov", "edu"} & set(parts):
        return out
    name = next((x for x in parts if x not in GENERIC_DOMAIN), "")
    if name:
        out["company_en"] = name.capitalize()
    return out


def _set_title(out, t, is_zh):
    if is_zh:
        m = DEPT_RE.match(t)
        if has_kw(t, COMPANY_STRONG):  # 「國立雲林科技大學博士生」是「單位+身分」，不拆部門（科技 ≠ 科）
            m = None
        if m and has_kw(t[m.end():], TITLE_KW):
            _add_dept(out, "department", m.group(1).strip())
            t = t[m.end():].strip()
        elif not has_kw(t, TITLE_KW):  # 只有部門
            _add_dept(out, "department", t)
            return
        _add_title(out, "title", t)
    else:
        segs = [x.strip() for x in t.split(",") if x.strip()]
        if len(segs) > 1 and has_kw(segs[0], TITLE_KW) and has_kw(" ".join(segs[1:]), DEPT_EN_WORDS):
            _add_title(out, "title_en", segs[0])      # "Staff, Sales and Marketing Center"
            _add_dept(out, "department_en", ", ".join(segs[1:]))
            return
        if has_kw(t, DEPT_EN_WORDS) and not has_kw(t, TITLE_KW):
            _add_dept(out, "department_en", t.rstrip(","))
            return
        m = re.match(r"^(.*\S)\s+([A-Z]{2,4})$", t)
        if m and not has_kw(m.group(2), TITLE_KW) and has_kw(m.group(1), TITLE_KW) \
                and not re.search(r"[AEIOU]", m.group(2)):  # 縮寫通常沒有母音（KCG），LAW / AT 是單字
            out["other"].append(m.group(2))  # 尾巴的 logo 縮寫（KCG）
            t = m.group(1)
        _add_title(out, "title_en", t)


def _add_title(out, key, t):
    """第一個職稱放 title，其餘（兼任、其他頭銜）放 other，不丟掉。"""
    if not out[key]:
        out[key] = t
    elif re.search(r"(?:暨|兼|及|、|&|,|and)$", out[key]):  # 「共同創辦人暨 / 營運總監」
        out[key] += ("" if re.search(f"[{CJK}]$", out[key]) else " ") + t
    elif t != out[key]:
        out["other"].append(t)


def _add_dept(out, key, t):
    """部門常分兩行（事業部 / 業務行銷中心）→ 串起來。"""
    t = t.rstrip(", ")
    if not out[key]:
        out[key] = t
    elif t not in out[key]:
        out[key] += (" " if key == "department" else ", ") + t


def _next_is(items, k, pred):
    return k + 1 < len(items) and not items[k + 1]["used"] and pred(items[k + 1]["text"])


def _absorb(items, k, text, pred, sep, limit=3):
    """把第 k 行後面、左緣對齊、符合 pred 的續行併進來（多行地址）。
    左右兩欄交錯排列時（地址在右欄、電話/email 在左欄），跳過不同欄的行。"""
    start = items[k]
    j, taken, skipped = k + 1, 0, 0
    while j < len(items) and taken < limit and skipped <= 4:
        it = items[j]
        aligned = abs(it["x"] - start["x"]) < 2.5 * max(8, start["h"])
        if it["used"] or not aligned:
            j, skipped = j + 1, skipped + 1  # 別欄的字
            continue
        if not pred(it["text"]):
            break
        cont_word = re.match(r"(?:Dist|District|Rd|Road|St|Street|Ave|Blvd|Ln|Aly)\b", it["text"])  # 斷在地名中間
        if not sep:
            text = text + it["text"]
        elif cont_word and not text.rstrip().endswith(","):
            text = text.rstrip() + " " + it["text"]
        else:
            text = text.rstrip(", ") + ", " + it["text"]
        it["used"] = True
        j, taken = j + 1, taken + 1
    return text.rstrip(", ")


def _is_zh_addr_cont(t):
    if re.search(r"統一編號|統編|電話|傳真|手機|行動|信箱|電郵|網址", t):
        return False
    return bool(re.search(f"[{CJK}]", t)) and bool(ZH_ADDR_CONT_RE.search(t)) and "@" not in t \
        and len(t) <= 25 and not has_kw(t, TITLE_KW) and not company_strength(t)


def _is_en_addr_cont(t):
    return not re.search(f"[{CJK}]", t) and bool(EN_ADDR_CONT_RE.search(t)) and "@" not in t \
        and strip_label(t)[0] not in ("phone", "mobile", "fax", "email") and not EMAIL_RE.search(t)


def _en_name_ok(t):
    return not any(w.lower().strip(".,") in EN_NOT_NAME for w in t.split())


def _email_hits(name, emails):
    locals_ = " ".join(e.split("@")[0].lower() for e in emails)
    return sum(1 for w in re.split(r"[\s\-]+", name.lower()) if len(w) >= 3 and w in locals_)


def _personal_score(d):
    """這一面有多少「個人」資訊；logo / 標語面通常是 0。"""
    return (2 * bool(d.get("name")) + 2 * bool(d.get("name_en")) + bool(d.get("title")) + bool(d.get("title_en"))
            + len(d.get("email", [])) + len(d.get("mobile", [])) + len(d.get("phone", [])))


ZH_FIELDS = ("name", "title", "department", "company", "address")
EN_FIELDS = ("name_en", "title_en", "department_en", "company_en", "address_en")


def _zh_ratio(d):
    txt = " ".join(v if isinstance(v, str) else " ".join(v) for v in d.values())
    zh, en = len(re.findall(f"[{CJK}]", txt)), len(re.findall(r"[A-Za-z]", txt))
    return zh / max(1, zh + en)


def merge_sides(front: dict, back: dict) -> dict:
    """合併正反面。
    - 一面中文、一面英文（常見）：中文欄位取中文面、英文欄位取英文面，另一面只補空白。
    - 否則個人資訊較多的那面優先（使用者常把 logo 面當正面上傳）。
    多值欄位取聯集（電話依正規化去重）。"""
    zf, zb = _zh_ratio(front), _zh_ratio(back)
    if abs(zf - zb) > 0.3 and _personal_score(front) and _personal_score(back):
        zh_side, en_side = (front, back) if zf > zb else (back, front)
        out = merge_sides_simple(zh_side, en_side)
        for k in EN_FIELDS:
            if en_side.get(k):
                out[k] = en_side[k]
        return out
    if _personal_score(back) > _personal_score(front):
        front, back = back, front
    return merge_sides_simple(front, back)


def merge_sides_simple(front: dict, back: dict) -> dict:
    out = dict(front)
    for k, v in back.items():
        if isinstance(v, list):
            cur = list(front.get(k) or [])
            if k in ("mobile", "phone", "fax"):
                keys = {phone_key(x) for f in ("mobile", "phone", "fax") for x in front.get(f, [])}
                cur += [x for x in v if phone_key(x) not in keys]
            else:
                cur += [x for x in v if x not in cur]
            out[k] = cur
        elif v and not front.get(k):
            out[k] = v
    return out
