# 名片管理系統

名片圖片 → 本機 OCR → 規則式欄位解析 → JSON + SQLite 資料庫 → 網頁檢索 / 編輯。
**完全離線、不呼叫任何 AI API（零 token 成本）**。

## 技術選型

| 元件 | 選用 | 說明 |
|---|---|---|
| OCR | [RapidAI/RapidOCR](https://github.com/RapidAI/RapidOCR)（clone 於 `vendor/RapidOCR`） | PaddleOCR **PP-OCRv6** 模型的 ONNX 版，繁中/英文辨識佳；Mac（M 系列 CPU）每面約 1.5–2 秒，正反面同時辨識 |
| 名片定位 | OpenCV | 以文字為錨點：判斷方向（直拿 / 上下顛倒 / 直書）→ 依文字角度轉正 → 往外找名片邊緣裁切；鍵盤字、背景名片自動排除 |
| 欄位解析 | `app/parser.py` 規則式 | 正規表示式 + 關鍵字字典 + 字體大小判斷姓名 |
| 資料庫 | SQLite (`data/cards.db`) | 免安裝；多關鍵字 AND 檢索、電話純數字檢索 |
| 後端 / 前端 | FastAPI + 單頁 HTML | 正面/反面分開拖曳上傳、整頁 4×2 拍照、檢索、標籤（自由索引）、合作可能性與公司篩選、編輯校正、匯出 JSON |

## 啟動

```bash
./run.sh            # 開 http://localhost:8000，同網段同事可用 http://<這台電腦IP>:8000
./run.sh --reload   # 開發用：改程式自動重載
```

首次執行會自動下載 OCR 模型（約 15 MB，來自 ModelScope）。

## 命令列：圖片 → JSON

```bash
source .venv/bin/activate
python -m app.cli card.jpg                      # 印出 JSON
python -m app.cli photos/*.jpg -o output_json   # 每張輸出一個 .json
python -m app.cli photos/*.jpg --save           # 同時存入資料庫
```

## 輸出 JSON 欄位

`name` `name_en` `title` `title_en` `department` `company` `company_en`
`mobile[]` `phone[]` `fax[]` `email[]` `website[]` `address` `address_en`
`tax_id`（統一編號） `line_id` `wechat` `other[]`（未分類文字） `tags[]`（標籤） `potential`（合作可能性 1~5 分，`null` = 未評估） `tags` `note`
`uploaded_at`（上傳時間） `updated_at` `image` `back_image` `ocr_lines[]` `ocr_lines_back[]`（正/反面原始 OCR 文字）

**正反面合併規則**：
- 一面中文、一面英文（最常見）：中文欄位（姓名、公司、職稱、部門、地址）取中文面，英文欄位取英文面。
- 否則「個人資訊」較多的那面優先（使用者常把 logo 面當正面上傳），另一面只補空白欄位。
- 電話 / Email 等多值欄位取聯集；電話正規化後去重（+886-2-… 與 02-… 視為同一支）。

每張名片存檔後同時寫出 `data/json/card_<id>.json`；網頁上可單張下載或「匯出 JSON」（依目前搜尋條件）。

## 標籤（自由索引）

自己定義分類，例如「金融業」「餐廳」「外館」「2026 展會」：

- **左側「標籤（自由索引）」**：列出所有標籤與名片數；每個標籤有勾選盒，主欄位顯示「有任一個被勾選標籤」的名片（可同時勾多個）；「尚未加標籤」也可以勾，找出還沒分類的名片；「全部名片」取消所有勾選。滑過標籤可「改名」或「刪除」（只移除標籤，不刪名片）。
- **批次加標籤**：勾選名片左上角方塊（可「全選目前結果」）→ 上方輸入標籤 →「加上標籤」/「移除標籤」。同一張名片可以重複操作加上多個標籤（會累加，不會覆蓋）。
- **單張編輯**：名片詳情的「標籤」欄一次輸入一個標籤、按 Enter 加入（輸入的整串就是一個標籤，不會自動拆開）；會提示既有標籤，避免同一類寫成兩種。一張名片可以有多個標籤。
- 標籤完全比對（「金融業」不會命中「非金融業」），搜尋框打標籤也搜得到；匯出 JSON 的 `tags` 是陣列。

## 公司名稱判斷規則（`app/parser.py`）

1. 電話、Email、網址、地址、統編等格式明確的行先排除。
2. 其餘每行算「公司強度」：
   - **強**（`COMPANY_STRONG`）：公司、金控、銀行、委員會、雜誌、通訊社、市政府、大學、Inc、Ltd、Corp、Bank…
   - **弱**（`COMPANY_WEAK`）：中心、媒體、影音、國際、Group、Media、Center…（常見於部門名）
   - 以 部/處/課/組/室/科/學系 結尾 → 部門，不算公司；含職稱字眼（Leader、Manager、委員…）且無法定後綴 → 職稱。
3. 中、英文各挑一個：強 > 弱 → 字最大 → 最上面。
4. 組織名下一行若是「…局 / 署 / 分行 / 分公司」會併入（臺北市政府 + 青年局）；拆成多行的全大寫英文會接回（TAIPEI CITY + GOVERNMENT）。
5. 正反面都沒公司 → 用 Email 網域猜（gov/edu 與免費信箱不猜）。

英文關鍵字一律**整字、不分大小寫**比對（`Principal` 不會命中 `inc`），新增關鍵字請寫小寫。
改規則後跑回歸測試與真實名片評估：

```bash
source .venv/bin/activate
python -m pytest tests/ -q                 # 單元測試
python -m tests.eval_real --set all        # 真實名片逐欄位比對（正解：tests/ground_truth*.json）
```

目前真實名片評估：20 張（40 面）、280 個欄位，正確 277（99%）。剩下 3 個是 OCR 認錯字（金箔字、特殊字型 logo）。

規則改了以後，舊名片可在網頁詳情按「依最新規則重新解析」（從原始照片重新辨識；標籤、備註、合作可能性保留）。

## API

| Method | Path | 說明 |
|---|---|---|
| POST | `/api/cards` | multipart `front`（可多張）+ `back`（選填，依順序配對）上傳並解析 |
| POST | `/api/cards/{id}/back` | 替既有名片補上 / 更換反面 |
| POST | `/api/cards/{id}/reparse` | 用最新規則重新解析（保留標籤、備註、合作可能性） |
| GET | `/api/potentials` | 各合作可能性的名片數 |
| GET | `/api/tags` | 所有標籤與名片數（自由索引） |
| POST | `/api/cards/tags` | 批次加 / 移除標籤：`{"ids": [1,2], "add": ["金融業"], "remove": []}` |
| POST | `/api/sheets` | 整頁模式：`front` / `back` 整頁照片 + `rows` / `cols` / `mirror` |
| GET | `/api/cards?q=&company=&potential=&tag=&tag_mode=&date_from=&date_to=&sort=` | 檢索（tag 可多個，`tag_mode=all` 全部都要有（預設）、`any` 有一個就好；`tag=__none__` = 尚未加標籤；potential 空字串 = 未評估；日期 YYYY-MM-DD；sort = new / old / potential） |
| GET/PUT/DELETE | `/api/cards/{id}` | 取得 / 修正 / 刪除 |
| GET | `/api/cards/{id}/json` | 下載單張 JSON |
| GET | `/api/export.json?q=` | 匯出全部（或檢索結果） |

## 目錄

```
app/ocr.py        OCR + 方向判斷 + 名片裁切 + 同列文字合併
app/pipeline.py   正反面辨識與合併（網頁、評估共用）
app/parser.py     欄位解析規則（要調整辨識邏輯改這裡）
app/db.py         SQLite
app/main.py       API
app/static/       前端
vendor/RapidOCR   OCR 原始碼（git clone）
data/             資料庫、圖片、JSON（備份這個資料夾即可）
samples/          測試名片（不進版控；python tools/make_samples.py 可產生合成名片）
```

## 已知限制

- 規則式解析遇到特殊版面可能分錯欄位，網頁上可直接修正後儲存。
- 無登入權限控管，請只在公司內網使用。
