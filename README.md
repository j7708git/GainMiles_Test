# GainMiles Python Online Test — 商品 API

目前只有架構規劃與開發需求文件，**尚未實作，不能啟動服務**。

## 文件入口

- [開發需求與驗收](docs/development-requirements.md)
- [技術選擇、資料模型與取捨](docs/technical-decisions.md)
- [code 作主鍵的 migration 備案規劃](docs/code-primary-key-alternative.md)（未啟用、沒有可執行 migration）
- [架構圖](docs/architecture.html)（規劃，不代表已實作）

預定使用 FastAPI + SQLAlchemy + PostgreSQL。資料庫透過 Docker 執行；Python 本機執行為基本交付，app Docker 容器為可選加分，同一份原始碼不分兩套。

預設商品仍用 id 主鍵與 code 唯一；另保留無商品 id 的備案文件，不混入預設 migration。sizes/colors 預定兼容 JSON 陣列和 `"Blue、Red"` 分隔字串，回應始終陣列，詳細驗證規則見需求文件。

## 啟動方式的交付要求

實作完成後本頁必須提供「從乾淨環境開始」的完整命令：設定環境變數、啟動資料庫、安裝 Python 依賴、執行資料表遷移、啟動 API、載入範例、執行測試、停止服務與保留資料說明。兩種模式的預定流程見需求文件；目前文件內的命令是**未驗證的設計契約**，不是已可執行的功能。

題目要求 AI 使用者提供完整對話。交卷時另附經檢查的完整 AI 對話附件，不以此 README、技術摘要或需求文件取代。原始題目與對話不預設公開到 GitHub。
