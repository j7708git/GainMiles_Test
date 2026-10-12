# Postman — GainMiles Product API

以 Postman 測試本專案商品 API 的 collection 與環境設定。

## 檔案

| 檔案 | 用途 |
| --- | --- |
| `GainMiles-Product-API.postman_collection.json` | Postman Collection v2.1：商品 CRUD、分頁、錯誤案例與 OpenAPI 文件，每個請求都附帶測試指令碼 |
| `GainMiles-Local.postman_environment.json` | 環境變數（`baseUrl`），預設指向 `http://127.0.0.1:8123` |

## 匯入方式

- **Postman 桌面版 / 網頁版**：File → Import，將上面兩個 JSON 檔一併拖入。
- **VS Code 的 Postman 擴充套件**：在 Collections 側邊欄選擇 Import，或直接把檔案加進 Local 資料夾。

匯入後，記得在右上角將環境切換為 **GainMiles Local**。

## 前置：先把服務跑起來

```bash
python setup_env.py
docker compose -p gainmiles-test up -d --wait --wait-timeout 120 db
alembic upgrade head
python -m app.seed          # 可選：載入四筆範例商品
uvicorn app.main:app --host 127.0.0.1 --port 8123
```

若服務不是跑在 `8123`，只要改環境變數 `baseUrl` 即可（例如 `--port 8124` 就改成
`http://127.0.0.1:8124`），不需要動 collection。

## 建議執行順序

Collection 內的資料夾順序即為建議順序，重點如下：

1. **Create** — 建立 demo 商品；回應的 `id` 會存入 collection 變數 `productId`，
   `code` 會存入 `createdCode`。`code` 由 collection 層級的前置指令碼以亂數產生
   （`DEMO-` + 16 個十六進位字元），不會與種子資料衝突。
2. **Error cases** — 409 / 422 契約；其中 409 需要一個已存在的 `code`，會沿用
   `createdCode`（若單獨執行則回退為種子代碼 `A-001`）。
3. **Read one / Update / Delete** — 使用 `productId` 讀取、替換、刪除。
   `Delete` 之後再讀取會得到 404。

> **注意**：`PUT` 會**全部替換**，包含 `code`。因此請先執行 `Update`，再執行
> `Delete`；`Delete` 放在最後。

## 用 Collection Runner 一次跑完

點選 collection → Run，選擇 **GainMiles Local** 環境，直接 Run，即可依序驗證
所有請求的測試。第一次執行前請確認服務與資料庫已就緒。

## 變數

| 變數 | 位置 | 說明 |
| --- | --- | --- |
| `baseUrl` | 環境 | 服務位址，預設 `http://127.0.0.1:8123` |
| `productId` | Collection | 由 Create 寫入，供後續請求使用 |
| `createdCode` | Collection | 由 Create 寫入，供 409 案例使用 |
| `demoCode` / `demoName` | Collection | 每個請求前由前置指令碼重新產生 |

> 刻意**沒有**把 `productId` 放進環境：環境變數優先順序高於 collection 變數，
> 若放進環境會讓 Create 寫入的值被覆蓋。
