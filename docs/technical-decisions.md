# 技術選擇與架構理由

日期：2026-10-12。狀態：規劃稿，尚未實作。

## 1. 題目解讀

題目要求商品 JSON REST API 的新增、讀取、修改、刪除；以 Docker 安裝關聯式資料庫；README 提供服務啟動命令；使用 AI 則附完整對話。沒有指定 Python 框架、RDBMS 品牌、API 欄位名稱、是否拆表、索引、容器化 app 或每個尺寸／顏色組合的庫存。

表格是業務資料範例，**不是要求資料庫只能有一張表**。關聯式資料庫也不代表每個文字欄位必須拆表。拆不拆應由「有沒有多值、是否共用、是否需維持一致」決定，而不是表越多越好。

## 2. 技術清單

| 選擇 | 理由 | 好處與代價 |
| --- | --- | --- |
| Python 3.12 作主要交付基線；保留 3.10 相容可能性 | 題目沒限定版本，不把作者電腦的既有版本當考官環境 | 本機需有 3.12；Docker 與本機主驗收用同一版本。不得自動改系統 Python |
| FastAPI + Pydantic v2 | JSON API、型別驗證與互動文件現成 | 減少手寫驗證；需理解驗證和金額序列化 |
| Uvicorn | 啟動 FastAPI 的標準服務程序 | 小型交付用單一程序；不是正式網際網路部署方案 |
| SQLAlchemy 2.0.x 同步模式 + psycopg 3 | 成熟 ORM（以 Python 操作資料表）與 PostgreSQL 驅動；2.0 可支援既有 Python 3.10 | 不引入非同步資料庫複雜度；Session 每請求建立與釋放 |
| Alembic | migration（記錄並執行資料表結構變更） | 結構可重建與追蹤；比啟動時 create_all 多一個命令 |
| PostgreSQL 18 官方 Docker image | 完整外鍵、唯一約束、精確金額與交易功能 | 不是唯一符合題目的選擇；MySQL 也可，SQLite 不作主要交付 |
| Docker Compose v2 | 描述資料庫與可選 app 容器，統一環境 | 需 Docker；不引入 Kubernetes、Redis 或管理介面 |
| pytest + httpx/TestClient | 驗證 REST 行為與錯誤情境 | 整合測試用真 PostgreSQL，而非用 SQLite 假裝相同 |
| pip + venv、精確版本依賴檔 | 考官能用熟悉的 Python 工具 | 不要求先安裝額外套件管理工具；交付前鎖定直接與間接依賴 |

2026-10-12 官方套件資訊：FastAPI 0.143.0、SQLAlchemy 2.1.4（需 Python ≥3.11）、Alembic 1.20.0、psycopg 3.3.6、Pydantic 2.14.1；本案選 SQLAlchemy **2.0 維護線**而非 2.1。其餘精確鎖定版本需實作時解析並在兩種啟動環境驗證，不能把「能解析依賴」當「服務已測試」。不使用無界限的最新版或資料庫 `latest` 標籤。

FastAPI 官方支援同步 `def` API 路由配合同步資料庫操作，會由外部執行緒池執行。不要在 `async def` 中直接呼叫同步 DB 而阻塞；也不共享全域 Session。

### 為什麼不是其他框架？

- Django／DRF：若需要後台、帳號、權限或團隊已有 Django 基礎，會很合理。本題沒有這些需求，先不引入較大的框架組合。
- Flask：可完成題目，但驗證、OpenAPI 文件與 ORM 的組合要自行選配。這裡選 FastAPI 是省去組裝工作，不是宣稱 Flask 無法做好。
- 非同步 ORM：題目沒有大量併發要求，同步 CRUD 的可讀性與驗收價值更高。

## 3. Docker：兩種啟動，不是兩份版本

**基本：Python 本機 + Docker db。加分：Docker app + Docker db。** 程式碼、模型、遷移與測試完全共用。

| 模式 | Python 執行位置 | 資料庫連線主機 | README 定位 |
| --- | --- | --- | --- |
| 基本 | 本機 venv | `localhost`（db 容器對本機映射的埠） | 先完成、必須能從零執行 |
| 加分 | Compose app 服務 | `db:5432`（容器內服務名稱） | 同樣完整驗證後才宣告支援 |

`.env` 放本機連線資訊且不提交；Compose 對 app 明確覆寫容器用 `DATABASE_URL`，避免 app 把自己的 localhost 當資料庫。提供 `.env.example`，只能含空值或 placeholder，不硬寫測試密碼。

`db` 常駐，`app` 放 `app` profile（按需啟用的一組容器），讓只開 DB 不必建 app。使用 healthcheck 等待資料庫可連線。healthcheck 不等於已建好資料表；Alembic 另執行，成功後才啟動 API。`docker-entrypoint-initdb.d` 只在空資料目錄第一次初始化執行，不能代替日後 migration。

PostgreSQL 18 官方 image 的 named volume（Docker 管理的持久化空間）掛載到 **`/var/lib/postgresql`**，不要照抄 17 以前的 `/var/lib/postgresql/data`。這是容器內公開標準路徑，不是個人電腦路徑。重建容器不得遺失資料；刪 volume 的指令需另行警告，不放一般停止流程。

本機映射 DB 與 API 埠只綁 `127.0.0.1`，app 容器內服務需 listen `0.0.0.0`。本題無登入，不能默認對外開放。

## 4. 資料表：保留欄位意義，拆多值與共用屬性

採 **六張表**：

```text
categories 1 ── N products
products   1 ── N product_sizes  N ── 1 sizes
products   1 ── N product_colors N ── 1 colors
```

| 表 | 角色 | 為什麼這樣拆 |
| --- | --- | --- |
| products | 商品名稱、code、分類外鍵、價格、總庫存 | 保留一筆商品的核心資訊 |
| categories | 共用分類名稱 | 避免同一分類重複與未來改名不一致；但本題單存字串也合理 |
| sizes | 共用尺寸代碼 | 尺寸是多值且跨商品重複 |
| colors | 共用顏色名稱 | 顏色是多值且跨商品重複 |
| product_sizes | 商品與尺寸的配對 | 商品可有多尺寸，尺寸可屬於多商品 |
| product_colors | 商品與顏色的配對 | 商品可有多顏色，顏色可屬於多商品 |

尺寸不存 `"S、M"` 的拼接文字：難以精準查詢、去重與約束。JSONB/ARRAY 在 PostgreSQL 可以用且不違反「使用 RDBMS」，但本案選關聯表，是為了展示外鍵與多對多設計，不是說 JSONB 一定錯。

**精簡替代方案**：若截止時間非常短，可用 products.category 字串，以及 `(product_id, size)`、`(product_id, color)` 兩張子表，總共三表；仍能避免拼接多值。代價是沒有共用屬性的識別與管理。六表是本案的建議，不是題目的硬性要求；不假設考官一定以表數評分。

### 不建 variants 的原因

Star 只有「尺寸 S、M」「顏色 Red、Blue」「總庫存 20」。不知道是不是四種組合都存在，也不知道每組數量。不能替題目捏造 S-Red 5 件、M-Blue 5 件等資料。因此 `unit_price`、`inventory` 留商品層，兩個集合獨立，**不表示任意尺寸×顏色一定可購買**。

未來若有每組合的價格庫存需求，再增加 product_variants，屆時需取得真實組合與庫存資料，不在本輪做。

### API 不必洩露內部拆表

API 接收 `category: "cloth"`、`sizes: ["S","M"]`、`colors: ["Red","Blue"]`。服務在同一交易（全部成功才寫入）中取得或建立屬性，再寫 products 與映射。屬性名不限定題目範例；不需額外 category/size/color CRUD 管理 API。以 UNIQUE 與衝突處理保證兩個請求新增同名屬性不會重複。

### 商品 id 與 code 的選擇

題目沒有指定主鍵；採 products.id PK + code UNIQUE 的理由是內部識別穩定，商品改編碼不連帶更改外鍵與 URL。不是把 id 誤認為題目欄位，也不宣稱不能用 code 作主鍵。

另存 [code 主鍵備案](code-primary-key-alternative.md)，涵蓋完全不設商品 id 的 schema、互斥 migration 隔離和 code API 差異；預設不啟用。若只把 code 設 PK 卻保留 id UNIQUE，數字 id API 可以保留；若真的拿掉 id，ORM／外鍵／端點／回應／排序也要改，不能只換 migration。

### sizes/colors：寬容輸入，統一輸出與儲存

原規格只允許陣列，尚未涵蓋前端傳 `"Blue、Red"` 的情況。現更新為接受陣列或分隔字串：API 入口依 `、`、`,`、`，` 切分並 trim，正規化成陣列，通過一致驗證後才寫關聯表；回應始終是排序陣列。

這是輸入格式相容，不是把資料庫退回存字串。代價是多一段明確的解析／驗證、OpenAPI input 與 output schema 分開，且標籤本身不得含三個分隔符；空項、重複及含分隔符的陣列元素不猜測處理，回 422。詳細規則與例子見 [需求 §5](development-requirements.md#5-json-欄位契約)。

## 5. 索引：先最小，再看查詢

索引像資料的目錄，能減少搜尋；代價是佔空間且寫入也需更新。四筆資料不會因此有可量測的重大加速，不能誇稱「提升幾倍」。

**核心必備（由約束自動建立，不另建重複索引）：**

- 各主檔 `id` 主鍵；products.code 唯一。
- categories.name、sizes.code、colors.name 唯一。
- product_sizes `(product_id, size_id)`、product_colors `(product_id, color_id)` 複合主鍵，避免重複配對並支援以商品找屬性。

**若交付 category/size/color 篩選，補三個 B-tree 索引：**

- `products(category_id)`。
- `product_sizes(size_id)`。
- `product_colors(color_id)`。

PostgreSQL 不會替外鍵欄位自動建索引。複合主鍵以 product_id 開頭，不能當作反向屬性查商品的通用替代。這些是依預定 exact filter 的設計，不是所有外鍵一律要加。

本輪不加價格、庫存、名稱全文、複雜複合索引或 GIN。日後資料量與查詢確定後，用 EXPLAIN ANALYZE（實際查看查詢如何執行）再決定。少量資料走全表掃描不算索引失敗。

## 6. 價格與一致性

- PostgreSQL 用 `NUMERIC(10,2)`，Python 用 Decimal（十進位精確數字），不以 float 存錢。
- API 接受 JSON 數字 `200` 或十進位字串 `"200.00"`；統一輸出 **`"200.00"` 字串**。JSON 沒有精確 Decimal 型別，Pydantic v2 也預設這樣輸出；這是明文契約，不是題目規定。
- API 拒絕非有限值、負值、不能精確表示為兩位小數的值（如 200.001）或超出欄位上限；額外尾零可接受，不靠 DB 默默四捨五入。
- 庫存是非負整數，DB 也有 CHECK；不是訂單扣庫存服務。
- 資料寫入一次交易；失敗回滾，不能只寫商品卻漏尺寸顏色。
- PUT/PATCH 可鎖定商品列直到寫入完成，避免同時替換映射留下混合集合；本題不做版本號、ETag 或庫存扣減 API。先後提交的絕對庫存更新仍是後寫者覆蓋，不宣稱具備電商交易安全。

## 7. 不做的事

不做登入、角色權限、前端網站、訂單、付款、分類後台、variant 庫存、微服務、快取、訊息佇列或雲端部署。刪除商品是真正刪除，不引入軟刪除與稽核日誌。

## 8. 官方依據

以下於 2026-10-12 查證；版本與文件會變動，實作前應確認鎖定組合。

- [FastAPI：同步與非同步](https://fastapi.tiangolo.com/async/)
- [FastAPI：資料庫教學與遷移提示](https://fastapi.tiangolo.com/tutorial/sql-databases/)
- [SQLAlchemy 2.0：多對多關聯](https://docs.sqlalchemy.org/en/20/orm/basic_relationships.html)
- [SQLAlchemy：發布維護線](https://www.sqlalchemy.org/download.html)
- [Pydantic：Decimal 驗證與 JSON 序列化](https://docs.pydantic.dev/latest/api/standard_library_types/)
- [Pydantic：before validators 與 input JSON Schema](https://docs.pydantic.dev/latest/concepts/validators/)
- [PostgreSQL：精確數字](https://www.postgresql.org/docs/18/datatype-numeric.html)
- [PostgreSQL：外鍵、唯一與主鍵約束](https://www.postgresql.org/docs/18/ddl-constraints.html)
- [Docker Compose：等待服務就緒](https://docs.docker.com/compose/how-tos/startup-order/)
- [Docker Compose：profiles](https://docs.docker.com/compose/how-tos/profiles/)
- [PostgreSQL 官方 image：初始化及 volume](https://github.com/docker-library/docs/blob/master/postgres/README.md)
- [FastAPI 官方套件資訊](https://pypi.org/project/fastapi/)、[SQLAlchemy](https://pypi.org/project/SQLAlchemy/)、[Alembic](https://pypi.org/project/alembic/)、[psycopg](https://pypi.org/project/psycopg/)、[Pydantic](https://pypi.org/project/pydantic/)

架構圖正文採繁體中文；產生器固定操作介面與 HTML lang 回退為英文，不影響圖中業務文字。圖是規劃設計，不是已存在程式碼的反向分析。
