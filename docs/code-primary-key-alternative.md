# 用商品 code 當主鍵的備案

版本：0.1；日期：2026-10-12；狀態：**只有規劃，沒有可執行 migration，也沒有啟用備案**。

## 1. 題目是否要求 code 當主鍵？

題目列出商品欄位，但沒有宣告主鍵、不允許新增欄位或要求用 code 當主鍵。因此：

- products.id 主鍵 + code 唯一，符合目前看得到的明文要求。
- products.code 直接作主鍵，也能符合。
- 不知道考官未寫出的偏好，不能保證哪一種得分更高。

預設仍選 id：id 是不隨商品編碼改名而改變的內部識別，code 是可修改的業務編碼。若有考官補充要求「code 就是主鍵」或「商品不准多 id 欄位」，再選相應備案。

## 2. 先區分「id 不作主鍵」與「完全不要 id」

| 方案 | 商品鍵 | 映射的商品外鍵 | 數字 id API 是否可保留 |
| --- | --- | --- | --- |
| 預設 | id PRIMARY KEY；code UNIQUE | product_id → products.id | 可以，現有契約 |
| 保留 API 的折衷 | code PRIMARY KEY；id IDENTITY NOT NULL UNIQUE | product_id → products.id（唯一欄位也可被外鍵引用） | 可以，但 ORM 的主鍵映射與取資料方法仍須核對 |
| 無 id 的備案 | code PRIMARY KEY；不建立 products.id | product_code → products.code | 不可以透明保留；需按 code 定位商品 |

所以「只改資料庫主鍵，API 就完全不衝突」**只有保留穩定 id 識別等條件成立時才可能**。若移除 id，現有 `/products/{id}`、回應的 id、排序和程式取資料方式都需要調整。

本文件完整規劃第三種：**商品不設 id、code 作主鍵**，以涵蓋更嚴格的假想要求；折衷方案只列比較，不預設建立第三套 migration。分類、尺寸、顏色的 id 不受影響，這不是所有表都禁止 id。

## 3. 無 id 備案的六表

除下列差異，其餘欄位、金額／庫存約束、屬性管理、驗證和交易沿用 [開發需求](development-requirements.md)。

| 表 | 備案差異 |
| --- | --- |
| products | 移除 id；code VARCHAR(32) COLLATE "C" PRIMARY KEY，非空白；不再另建 code UNIQUE 索引 |
| product_sizes | product_id 改 product_code VARCHAR(32) COLLATE "C"；FK products.code ON UPDATE CASCADE ON DELETE CASCADE；PK(product_code,size_id) |
| product_colors | product_id 改 product_code VARCHAR(32) COLLATE "C"；FK products.code ON UPDATE CASCADE ON DELETE CASCADE；PK(product_code,color_id) |
| categories / sizes / colors | 保留原 id 與唯一文字欄位，不變 |

COLLATE "C" 固定商品編碼的大小寫敏感等值與排序，不隨資料庫地區設定改變；code 仍只要求 trim 後 1–32 字，不額外限制為 A-001 格式或只准英文。

`ON UPDATE CASCADE` 指「商品 code 改名時，資料庫連同更新引用它的配對」，不是另新增一個商品。SQLAlchemy 主鍵、relationship 與查詢須使用正確的備案 metadata；保持 DB 負責更新傳播，並以實際交易測試核對 ORM 讀回狀態。

映射複合主鍵已以 product_code 開頭，不另加重複的單欄 product_code 索引。若做尺寸／顏色篩選，反向 size_id/color_id 索引仍照需求加入；category_id 索引亦不變。

## 4. 備案 API 差異

其他產品欄位、狀態碼、JSON 行為和尺寸／顏色輸入相容性不變。**只有本備案啟用時**採以下契約，不與預設 numeric id API 假裝完全相同：

| 功能 | 備案定位方式 |
| --- | --- |
| 新增／列表 | POST /api/v1/products、GET /api/v1/products，不變 |
| 單筆讀取／全部更新／刪除 | GET / PUT / DELETE /api/v1/products/by-code?code=A-001 |
| 部分更新（有做才提供） | PATCH /api/v1/products/by-code?code=A-001 |
| 商品回應 | 保留原七欄，不回 id，也不捏造假 id |
| 列表 | 依 code COLLATE "C" 升序，再分頁；total 的語義不變 |

用 query parameter（網址問號後的參數）傳 code，而不是直接拼到路徑，避免為路徑安全擅自禁止 `/`、空白或中文編碼。客戶端應用 URL encoding 正確傳 `+`、`&`、`/`、中文等值；服務不再重複 URL decode，也不自動變更大小寫。code 缺失、空白、超長或重複 query 參數回 422；有效但不存在回 404。`by-code` 是固定路由，不保留 numeric-id catch-all 來誤接。

POST 成功 201，Location 指向 URL-encoded 的 by-code 查詢位置。PUT/PATCH 如把 `A-001` 改為 `A-003`：

1. 以舊 code 的 URL 定位並鎖定現有商品。
2. 同一交易更新商品、由外鍵 cascade 更新映射；若集合也修改，服務使用更新後的 code 替換映射，不用舊鍵留下孤兒。
3. 新 code 已存在：409，舊商品與所有關聯完全不變。
4. 成功：200，body 使用新 code；Location 指向新位置。
5. 舊 code 之後查詢回 404，新 code 可查；不保留舊編碼別名。

## 5. Migration 備案如何存放（未建立程式）

Migration 是用程式記錄資料表的建立與變更。目前本案沒有任何 migration，以下只是未來檔案配置與行為契約：

```text
alembic.ini                             # 預設：指向 migrations/
migrations/                             # 預設 id PK 的歷史
schema-alternatives/
└── code-primary-key/
    ├── alembic-codepk.ini               # 備案獨立設定
    ├── metadata.py                     # 備案六表定義，不匯入預設 app 主鍵模型
    └── migrations/
        ├── env.py
        └── versions/
            └── initial_code_pk.py      # 備案初始建表；目前不存在
```

- 預設 `alembic upgrade head` 不發現、也不套用備案歷史。
- 備案明確使用另外的設定檔，預定命令為 `alembic -c schema-alternatives/code-primary-key/alembic-codepk.ini upgrade head`；**尚不可執行、未驗證**。
- 備案讀獨立 `CODEPK_DATABASE_URL`，指定另外的空專用資料庫；不回退到 DATABASE_URL。執行前拒絕與預設資料庫相同的目標，或已存在不相容商品表／版號的目標。
- 兩環境各在自己的資料庫保存 alembic_version。**只有換設定檔或 script_location，不會自動隔離同一資料庫的版號與表。** 不在同一個資料庫依序執行兩套初始建表。
- upgrade 順序：categories/sizes/colors → products → 兩張映射；downgrade 反序，只限明確的新建測試 DB。downgrade 會刪資料，非一般切換方式，不得默默執行。
- 不把兩份互斥初始 revision 放進同一個預設 versions 目錄，也不使用 upgrade heads 或 merge 把它們混合套用。

這是「從空資料庫建立另一種設計」的備案，**不是已存在 id 資料庫的就地改造 migration**。後者需先備份、用 id→code 對照回填映射、檢查筆數與孤兒、替換約束並處理原 id 對外參照；本案沒有這種現成資料，也沒有授權做資料搬移或刪欄位。

若真的選備案，需同步改 ORM、商品定位、回應 schema、Location、排序、seed 與測試；不預設花時間長期維護兩套可熱切換的 app，也不把備案寫成「只要換 migration 就能跑」。

## 6. 備案未來驗收

1. 預設 migrations 仍只有自己的 head；不會建 code-only 表。
2. 空專用 DB 建六表；products 沒有 id，code 是唯一主鍵；字典 id 不變。
3. code 重複拒絕；映射不重複、不得引用不存在的 code。
4. 改 code 同步改兩映射，集合不變；同時改 code／集合可完整提交；衝突完整回滾。
5. 刪商品清映射、不刪共用屬性；四筆種子總庫存保持一致。
6. 選用備案的 app 按上述 code 契約 CRUD；numeric id 不能默默被當 code。特殊字元 query encoding／空白與長度／重複參數納入測試。
7. 新舊 Location、舊碼 404、新碼可讀、code 升序分頁和大小寫敏感可驗證。
8. 備案指到 default DB 或不相容 DB 時拒絕，且原有資料／revision 不改。

## 7. 官方依據

2026-10-12 文件查證，尚未執行 schema／ORM／API 測試：

- [PostgreSQL：主鍵、可引用唯一欄位的外鍵與 ON UPDATE CASCADE](https://www.postgresql.org/docs/18/ddl-constraints.html)
- [PostgreSQL：collation](https://www.postgresql.org/docs/18/collation.html)
- [SQLAlchemy 2.0：可變主鍵](https://docs.sqlalchemy.org/en/20/orm/relationship_persistence.html#mutable-primary-keys-update-cascades)
- [Alembic：獨立 migration 環境](https://alembic.sqlalchemy.org/en/latest/cookbook.html#run-multiple-alembic-environments-from-one-ini-file)
- [Alembic：多個 head 與分支](https://alembic.sqlalchemy.org/en/latest/branches.html)
