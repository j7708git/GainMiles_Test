# GainMiles Python Online Test — 商品 API

以 Python 實作的商品 JSON REST API：新增、讀取、列表分頁、全部替換與刪除，
資料庫使用 Docker 中的 PostgreSQL。本頁提供**從乾淨環境開始、可實際重現**的
完整命令，並說明已支援與尚未完成的功能。

- 已支援：`POST` / `GET`（單筆與列表分頁）/ `PUT` / `DELETE`；`sizes`、`colors`
  可接受 JSON 陣列或在實務上常見的分隔字串；四筆範例資料載入（`python -m app.seed`）；
  以真 PostgreSQL 執行的整合測試。
- 尚未支援：`PATCH` 部分更新、分類／尺寸／顏色的精確篩選查詢、對應的三個篩選索引、
  app 容器化（Docker profile）、以及「以商品 `code` 當主鍵」的 migration 備案。
  詳見[〈尚未完成與非目標〉](#9-尚未完成與非目標)。

- 需求與驗收契約：[docs/development-requirements.md](docs/development-requirements.md)
- 技術選擇與資料模型理由：[docs/technical-decisions.md](docs/technical-decisions.md)
- code 作主鍵的備案規劃（未啟用）：[docs/code-primary-key-alternative.md](docs/code-primary-key-alternative.md)
- 架構圖：[docs/architecture.html](docs/architecture.html)

> 這是筆試交付用的本機服務，只綁 `127.0.0.1`，**沒有登入、沒有 TLS、沒有防濫用**，
> 不是正式上線設定。

## 1. 環境需求

| 元件 | 版本 | 說明 |
| --- | --- | --- |
| Python | **3.12** | 本案主要交付基線；已在 3.12.14 驗證。專案以 venv 隔離，不改系統 Python |
| PostgreSQL | **18**（`postgres:18.6` 官方 image） | 由 Docker 執行，不用 SQLite 代替 |
| Docker Engine + Docker Compose CLI | `docker compose`（有空白；v2 以上，本頁語法在 v2 與較新的 v5 相同） | 資料庫以容器執行 |

Python 套件版本已精確鎖定於 `requirements*.txt`（版本固定、`pip` 可直接安裝）：

| 套件 | 版本 | 用途 |
| --- | --- | --- |
| `fastapi` | 0.143.0 | HTTP API 框架與 OpenAPI 文件 |
| `uvicorn[standard]` | 0.54.0 | 啟動 FastAPI 的服務程序 |
| `SQLAlchemy` | 2.0.54 | ORM（採 2.0 維護線，同步模式） |
| `psycopg[binary]` | 3.3.6 | PostgreSQL 驅動（`[binary]` 免本機編譯） |
| `alembic` | 1.20.0 | 資料表結構版本與遷移 |
| `pydantic` / `pydantic-settings` | 2.14.1 / 2.15.0 | 輸入輸出驗證與讀取 `.env` |
| `pytest` / `httpx` | 9.0.1 / 0.28.1 | 測試（僅開發依賴） |

**若機器上沒有 `python3.12`**：多數 Linux 發行版可直接安裝，或使用
[`uv`](https://docs.astral.sh/uv/) 取得一個獨立的 Python 3.12 runtime，
例如 `uv python install 3.12` 與 `uv python find 3.12`，再以其路徑建立 venv。
這只是**可選**做法，不會更動系統 Python；本專案本身不要求 uv。

## 2. 目錄結構

```text
.
├── app/
│   ├── main.py            # FastAPI 應用、錯誤處理
│   ├── config.py          # .env 設定與測試資料庫護欄
│   ├── db.py              # Engine、Session（每請求一個 Session）
│   ├── models.py          # 六張表的 SQLAlchemy 模型
│   ├── schemas.py         # 輸入輸出模型與驗證
│   ├── seed.py            # python -m app.seed 的入口
│   ├── routers/products.py
│   └── services/products.py
├── migrations/            # Alembic 遷移（初始 revision: 0001_initial）
├── tests/                 # 需要真 PostgreSQL 的整合測試與環境測試
├── docs/                  # 需求、技術決策、備案、架構圖
├── postman/               # Postman collection 與本機 environment（§11）
├── submission/            # 交卷附件：AI 對話快照 ZIP 與說明（§10）
├── alembic.ini
├── compose.yaml           # db 與 test profile 的 db_test
├── requirements.txt       # 執行期依賴（鎖定）
├── requirements-dev.txt   # 含執行期依賴 + 測試依賴（鎖定）
├── setup_env.py           # 產生 .env（純標準函式庫）
└── .env.example           # 範例設定（只有 placeholder，不是真密碼）
```

## 3. 從零啟動（本機 Python + Docker 資料庫）

以下命令都**在專案根目錄**執行（也就是本 README 所在目錄），並使用 POSIX shell
（Linux / macOS）。本頁未驗證 Windows 的完整流程。

### 步驟 1：產生 `.env`（不要手抄 placeholder 當密碼）

```bash
python3 setup_env.py
```

`setup_env.py` 只用 Python 標準函式庫，**不需要**先建立 venv。它會：

- 產生一組隨機的資料庫密碼（終端不顯示），並對密碼做 URL encode 後填入
  `DATABASE_URL` 與 `TEST_DATABASE_URL`；
- 讓 `POSTGRES_*`、host 埠與兩條連線 URL 保持對齊；
- 以 `0600` 權限建立 `.env`，且**拒絕覆寫已存在的 `.env`**（含符號連結）。

> `.env` 已在 `.gitignore` 中，請勿提交。**不要**複製 `.env.example` 後直接沿用
> `change-me` 當密碼——那只是範例 placeholder。

### 步驟 2：啟動資料庫容器

```bash
docker compose -p gainmiles-test up -d --wait --wait-timeout 120 db
```

`--wait` 會等到容器 healthcheck 通過才返回；compose 的 healthcheck 是用
`pg_isready`，確認資料庫可連線。**健康不等於已建好資料表**——資料表由下一步的
Alembic 建立。

預設把資料庫映射到 `127.0.0.1:55432`（只綁 loopback，不對外）。
容器內資料目錄使用命名 volume，掛載到 **`/var/lib/postgresql`**（PostgreSQL 18
官方 image 的路徑；舊版 image 的 `/var/lib/postgresql/data` 不適用）。

### 步驟 3：建立 venv 並安裝依賴

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` 已包含執行期依賴與測試依賴，**本機開發只需這一個檔案**。
若只要跑服務、不要測試工具，可改裝 `requirements.txt`（純執行期依賴）；
兩者皆為精確鎖定版本，請勿手動升版。

### 步驟 4：建立資料表（Alembic 遷移）

```bash
alembic upgrade head
```

`alembic.ini` 內不含任何密碼；`migrations/env.py` 會從 `.env` 讀取 `DATABASE_URL`，
因此請在專案根目錄執行。app 啟動時**不會**用 `create_all` 建表。

### 步驟 5：載入四筆範例資料

```bash
python -m app.seed
```

會載入下表四筆商品（`seeded 4 product(s), skipped 0 existing` 代表首次成功）。
此命令**可重複執行**：已存在的 `code` 會跳過、不覆寫、不刪除；第二次執行會顯示
`seeded 0 product(s), skipped 4 existing`。

| name | code | category | sizes | unit_price | inventory | colors |
| --- | --- | --- | --- | --- | --- | --- |
| Star | A-001 | cloth | S, M | 200.00 | 20 | Red, Blue |
| Moon | A-002 | cloth | M, L | 300.00 | 10 | Red, White |
| Eagle | B-001 | pants | M, L | 100.00 | 23 | Green |
| Bird | B-002 | pants | S, M, L | 50.00 | 12 | Black |

> 商品的 id 由伺服器以資料庫 identity 指派；**不要假設 Star 一定是 id 1**，
> 也不要在範例中硬寫 id。

### 步驟 6：啟動 API

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8123
```

- 互動式文件：<http://127.0.0.1:8123/docs>
- OpenAPI：<http://127.0.0.1:8123/openapi.json>
- 商品端點：`http://127.0.0.1:8123/api/v1/products`

本頁以 **8123** 為例（避免與其他常見服務搶 `8000`）。**若 8123 也被占用**，
換一個埠即可，例如 `--port 8124`，並把後續 `curl` 與瀏覽器網址一起改成 8124；
**不要**去終止既有服務。服務只綁 loopback。

## 4. 與 API 互動：完整 CRUD 範例（curl）

以下範例會**自建一個新的 demo 商品、讀取、替換、刪除、最後驗證 404**，且只動到
這個 demo 商品，四筆種子資料不受影響。demo 的 `code` 以隨機 uuid 產生（`DEMO-`
加 16 個十六進位字元，長度 21，未超過 32 字上限），與題目 seed 使用的 `A-001`、
`B-002` 等不會重複，可大幅降低衝突機率；但這只是降低機率，**不保證任何情況下都
不會出現 409**（真的撞到時，下一步的 `curl -f` 會直接失敗，而不是把錯誤內容誤當
成商品 JSON 去解析）。

```bash
# 專案內、已被 .gitignore 忽略的獨立暫存目錄（不覆寫任何既有檔案、不用系統 /tmp）
mkdir -p .tmp
TMPDIR=$(mktemp -d .tmp/crud.XXXXXX)

BASE=http://127.0.0.1:8123
API=$BASE/api/v1/products

# 以 uuid 產生 demo code（DEMO- + 16 個十六進位字元，共 21 字，<= 32 字上限）
DEMO_CODE="DEMO-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:16])')"

# 1) 新增（預期 201，回應標頭帶 Location）。
#    用 -f：非 2xx（例如不慎衝突的 409）會直接非 0 結束，避免誤解析 id。
curl -sS -f -D "$TMPDIR/post.headers" -o "$TMPDIR/post.json" \
  -w 'POST status: %{http_code}\n' \
  -X POST "$API" -H 'Content-Type: application/json' \
  -d "{\"name\":\"Demo\",\"code\":\"$DEMO_CODE\",\"category\":\"cloth\",\"sizes\":[\"S\",\"M\"],\"unit_price\":\"200.00\",\"inventory\":7,\"colors\":[\"Blue\",\"Red\"]}"
grep -i '^location:' "$TMPDIR/post.headers"

# 從 POST 回應解析伺服器指派的 id：檔案路徑以 argv 傳入，不拼進 Python 程式碼。
DEMO_ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$TMPDIR/post.json")
echo "id=$DEMO_ID"

# 2) 讀取單筆（預期 200）
curl -sS -f "$API/$DEMO_ID"

# 3) 全部替換七個欄位（預期 200）；集合也可用分隔字串輸入
curl -sS -f -X PUT "$API/$DEMO_ID" -H 'Content-Type: application/json' \
  -d "{\"name\":\"Demo Updated\",\"code\":\"$DEMO_CODE\",\"category\":\"pants\",\"sizes\":\"S、M\",\"unit_price\":199.5,\"inventory\":3,\"colors\":\"Red，Blue\"}"

# 4) 刪除（預期 204，無 body）
curl -sS -f -o /dev/null -w 'DELETE status: %{http_code}\n' -X DELETE "$API/$DEMO_ID"

# 5) 再讀一次（預期 404）。這一步刻意**不加** -f：預期中 404 會讓 -f 以非 0 結束，
#    而我們要看到的是錯誤 body，所以直接顯示回應與狀態碼。
curl -sS -w '\nstatus: %{http_code}\n' "$API/$DEMO_ID"
# 預期輸出：{"detail":"Product not found"}  以及 status: 404
```

新增成功的回應（`unit_price` 是兩位小數字串，集合固定排序）；
下面的 `id` 值**只是示例**，實際由伺服器指派：

```json
{
  "id": 5,
  "name": "Demo",
  "code": "DEMO-1a2b3c4d",
  "category": "cloth",
  "sizes": ["M", "S"],
  "unit_price": "200.00",
  "inventory": 7,
  "colors": ["Blue", "Red"]
}
```

> **`curl -f` 與預期中的 404**：若在上一步改用 `curl -f`，預期的 404 會讓 curl
> **結束碼非 0**（22）。那是 `-f` 的正常行為，不是腳本壞掉。要在 404 時仍看到
> 錯誤內容，請**不加** `-f`（如上面的範例）。

列表分頁（預設 `limit=20`、`offset=0`；`limit` 1–100、`offset` 0–100000）：

```bash
curl -sS "$API?limit=2&offset=0"
# {"items":[...],"total":4,"limit":2,"offset":0}
```

> `BASE` 與 `API` 這兩個變數只在**目前這個 shell** 有效。若把上面的片段分段貼到
> 不同的終端，請在該終端先重新設定 `BASE=http://127.0.0.1:8123` 與
> `API=$BASE/api/v1/products` 再執行。

## 5. 執行測試（專用測試資料庫）

整合測試需要一個**專用的 PostgreSQL 測試資料庫**，不會對應用資料庫做任何清空。

```bash
# 1) 啟動測試資料庫容器（test profile）
docker compose -p gainmiles-test --profile test up -d --wait db_test

# 2) 執行測試（venv 已啟用）
pytest -q
```

- `setup_env.py` 產生的 `TEST_DATABASE_URL` 預設指向
  `127.0.0.1:55433/gainmiles_test`（只綁 loopback），與應用資料庫分開。
- **護欄**：測試只有在 `TEST_DATABASE_URL` 指向專用資料庫時才會執行——資料庫名稱
  必須以 `_test` 結尾，且其 **host／port／database 三者正規化後的組合**必須與
  `DATABASE_URL` 不同。三者不必逐項都不同：主機相同、但資料庫名或埠不同即為合法
  的不同目標（`127.0.0.1` 與 `localhost` 會視為同一主機）。符合後，
  測試會對**測試庫**做 `TRUNCATE`；**絕不對應用資料庫 `TRUNCATE` 或 `DROP`**。
  若 `TEST_DATABASE_URL` 不安全，測試會直接失敗而非通過。
- **缺 URL 時的 skip 不算通過**：若 `TEST_DATABASE_URL` 未設定，需要資料庫的測試
  會被**略過（skip）**，而不是以 SQLite 假裝通過。要驗證真 PostgreSQL 行為，請
  先完成上面的測試庫設定，並確認輸出為 **0 skipped**。
- 測試輸出會出現一則 `StarletteDeprecationWarning`（Starlette 對 httpx 的相容提示）。
  依賴已固定，此警告目前**不影響測試結果**；若要更新相關依賴，需重新驗證整套流程。

## 6. 停止服務與保留資料

```bash
# 停止本機 API：在執行 uvicorn 的終端按 Ctrl+C

# 停止資料庫容器（保留 volume，資料不會遺失）
docker compose -p gainmiles-test --profile test down
```

- `down` **保留**命名 volume，下次 `up` 後資料仍在。
- **不要**把 `docker compose down -v` 當作正常停止步驟：`-v` 會刪除 volume，
  連帶清空資料，屬於破壞性操作。
- 重建容器時，資料因為儲存在 PostgreSQL 18 的命名 volume
  （掛載於容器內 `/var/lib/postgresql`）而保留。可用以下命令重建容器但保留資料；
  不要加入 `-v` 或另行刪除 volume。API 在重建期間可能暫時回 503，資料庫健康後可再讀取。

```bash
docker compose -p gainmiles-test --profile test up -d --force-recreate --wait --wait-timeout 120 db db_test
```

### 若 Docker 權限不足

若出現權限錯誤（例如 `permission denied` 連不到 Docker daemon），請**在您自己的
終端**以相同命令搭配 `sudo` 執行，例如：

```bash
sudo docker compose -p gainmiles-test up -d --wait --wait-timeout 120 db
```

請勿以修改 `docker` 群組或 `sudoers` 的方式放寬全機設定；也請勿把密碼貼到任何
對話或檔案中。

## 7. 資料庫 schema 與 API 契約（摘要）

六張表：`products`、`categories`、`sizes`、`colors`，以及兩張多對多映射
`product_sizes`、`product_colors`。

| 表 | 重點欄位與約束 |
| --- | --- |
| `products` | `id` PK（identity）；`code` **UNIQUE**；`category_id` FK；`unit_price` `NUMERIC(10,2)`，`0 ≤ 值 ≤ 99999999.99`；`inventory` 非負整數 |
| `categories` / `sizes` / `colors` | `id` PK；文字欄位 UNIQUE 且非空白 |
| `product_sizes` / `product_colors` | 複合 PK，FK 指向 `products` 與字典表；刪商品時連帶刪映射 |

**商品欄位（七個可寫欄位）**

| 題目欄位 | JSON 欄位 | 規則 |
| --- | --- | --- |
| Name | `name` | 字串，trim 後 1–128 字 |
| code | `code` | 字串，trim 後 1–32 字；唯一、大小寫敏感；**可修改，且修改後 `id` 不變**；不限制 `A-001` 格式 |
| category | `category` | 字串，trim 後 1–64 字；由寫入時取得或建立共用分類 |
| size | `sizes` | **輸入**：JSON 字串陣列或分隔字串；**輸出**：一律排序後的字串陣列 |
| Unit price | `unit_price` | **輸入**：數字或十進位字串；**輸出**：固定兩位小數字串（如 `"200.00"`）；拒絕負值、非有限值、多於兩位**有效**小數（尾零可接受，例如 `200.000` 視為 `200.00`）；不以 float 存錢 |
| inventory | `inventory` | 嚴格 JSON 整數，`0`–`2147483647`；拒絕布林、字串數字、小數 |
| color | `colors` | 同 `sizes`：輸入陣列或分隔字串，輸出排序後的陣列 |

- `sizes` / `colors` 的分隔符為 `、`、`,`、`，`（可混用）。陣列元素是完整標籤，
  不再逐項拆分；空項、重複值、或超出長度限制都會回 **422**，且不會寫入任何資料。
  回應一律是**排序後的陣列**，不跟隨輸入型態回字串。`"Blue"` 是一項；
  `"Blue Red"` 是一個標籤（不以空白拆分）。
- **id 範圍**：`/api/v1/products/{id}` 的 id 是 `1`–`2147483647` 的整數，超限回 422。
- **PUT 是全量替換**：一次替換全部七個可寫欄位，缺欄位或不合法回 422，查無回 404，
  code 衝突回 409；**不存在「只更新部分欄位」的 PATCH**。
- 錯誤回應：輸入不合法 `422`（FastAPI 標準 `detail` 陣列）；查無 `404`、
  code 衝突 `409` 用 `{"detail": "..."}`；資料庫不可用 `503`；未預期錯誤 `500`。
  回應**不會**洩漏 SQL、連線字串、堆疊或密碼。

更完整的欄位契約、驗證矩陣與邊界範例見
[docs/development-requirements.md](docs/development-requirements.md)。

## 8. 常見問題

- **埠 55432 / 55433 / 8123 已被占用**：前兩者是資料庫對本機的映射埠，後者是 API。
  可在**第一次** `setup_env.py` 之前修改 `.env.example` 的 `DB_HOST_PORT` /
  `DB_TEST_HOST_PORT` 非機密預設值，之後產生的 `.env` 會自動讓兩條 URL 對齊。
  若 `.env` 已存在，`setup_env.py` 會拒絕覆寫；此時請自行編輯 `.env`，**同時更新
  `DB_HOST_PORT`/`DB_TEST_HOST_PORT` 與對應的 `DATABASE_URL`/`TEST_DATABASE_URL`**，
  且**不要改動已存在資料庫的 `POSTGRES_PASSWORD`**。API 埠則改用 uvicorn
  `--port` 指定其他埠即可。
- **為什麼改密碼沒生效？** PostgreSQL 官方 image 的 `POSTGRES_PASSWORD` 只在
  **資料目錄第一次初始化（空 volume）時**才有效。對已初始化的資料庫改 `.env` 密碼
  不會改變資料庫內的角色密碼。本案**不建議**為此刪除 `.env` 或 volume；
  那會影響既有資料。
- **為什麼 `setup_env.py` 第二次執行失敗？** 這是刻意的：它拒絕覆寫既有 `.env`，
  以免不小心蓋掉你正在使用的密碼與連線設定。

## 9. 尚未完成與非目標

本次交付**只包含**：`POST` / `GET`（單筆與列表分頁）/ `PUT` / `DELETE`、
`sizes`/`colors` 兩種輸入型態、共用文字屬性的取得或建立、四筆 seed，以及對真
PostgreSQL 的整合測試。

**尚未實作**（若要使用，需另外開發，不在本次範圍）：

- `PATCH` 部分更新。
- 精確篩選查詢（`category` / `size` / `color`），以及支援它們的三個索引
  （`products(category_id)`、`product_sizes(size_id)`、`product_colors(color_id)`）。
- app 容器化（Compose `app` profile／`Dockerfile`／`.dockerignore`）。**不是一條
  `docker compose up` 就能連 API 一起啟動**：目前是「本機 Python 跑 API + Docker 跑
  資料庫」。
- 以商品 `code` 當主鍵的 migration（目前只有[公開規劃文件](docs/code-primary-key-alternative.md)，
  沒有可執行的 migration）。

**非目標**：登入／權限、前端、訂單、variant 級庫存、雲端部署。

## 10. AI 使用對話（附件）

題目要求提供使用 AI 的完整對話。本 repo 提供經確認可公開的
[AI 對話快照 ZIP](submission/ai-conversation-snapshot.zip)，下載與範圍說明見
[附件說明](submission/README.md)。本 README 與 `docs/` 不取代對話原文。

附件涵蓋打包時的主對話、研究與實作子對話、2026-10-13 的總體審查對話及相關畫面；它是**歷史快照**，
不包含打包之後的回覆，也不是未刪減的原生 session 匯出。交卷前應確認是否需要
更新對話，不能以現有快照宣稱包含所有未來往來。附件不含密碼檔、隱藏推理或原生工具全文；
專案的權威進度筆記、私人設定與憑證不在公開 repo 中。

## 11. Postman 操作檔案

[postman/](postman/README.md) 提供 Collection v2.1 與本機環境設定，可在 Postman 匯入後
測試商品 API。先依本頁啟動服務，再匯入下列兩個檔案並選擇 **GainMiles Local**：

- [商品 API collection](postman/GainMiles-Product-API.postman_collection.json)
- [本機 environment](postman/GainMiles-Local.postman_environment.json)

預設 `baseUrl` 為 `http://127.0.0.1:8123`；若 API 使用其他埠，請同步修改這個變數。
建議先建立 collection 的 demo 商品，再依其取得的 `productId` 執行更新與刪除，
避免操作既有商品。完整匯入方式與執行順序見 [Postman 說明](postman/README.md)。
