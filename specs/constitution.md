# slide-extractor 憲章

> 反向萃取自 2026-05-16 ~ 2026-05-17 的迭代軌跡。每條原則都對應一次真實事故或決策，不是空泛口號。

## 核心原則

### I. 演算法不能自證沒漏頁 — 人眼閉環是 SLA
任何「自動化 100% 不漏頁」的承諾都是謊言。同模板投影片、動畫漸進顯示、嵌入影片、OCR 誤讀都會吃掉自動模式的可靠性。**設計鐵則**：每一條輸出路徑都必須有一個人工 review 出口（`slide_review.py` / Web GUI 的 contact sheet）。使用者在 30 秒內視覺確認 == 真正的閉環。

> 證據：M2 影片 slide 11/12 是同主題的 intro/full 兩個動畫階段，jaccard 0.39 < 0.45 threshold 拆 cluster；OWASP Crypto 影片 32-33 之間漏頁；無論調參都不能 100% 解。

### II. 過收優於漏頁（Recall > Precision）
當演算法在「合併 / 拆 cluster」的邊界搖擺時，預設**拆**而不是合。多出來的候選用戶可以勾掉（30 秒）；漏掉的候選用戶可能根本不會發現（永久遺失）。

> 證據：slide 11 是 36 tokens 的 intro 階段，jaccard 0.39 對 92 tokens 的完整版 slide 12。演算法拆了，用戶選擇刪 11 — 損失成本 = 一次點擊；如果合了，用戶不會知道 intro 版本曾存在 — 損失成本 = 看影片重抓。

### III. 工具不授權內容（License of Code ≠ License of Output）
slide-extractor 的程式碼是 MIT，但這不代表「使用者用它生出的 PPTX」也能任意散布。著作權聲明（NOTICE / README / Web UI / CLI `--help`）必須四個地方同步出現，把責任明確劃到使用者身上。

> 證據：yt-dlp 是 Unlicense（公領域），但拿 yt-dlp 下載有版權的影片不會讓那部影片變公領域。

### IV. 適用範圍要寫死，不能含糊（Honest Scope）
工具是「典型投影片型講演」的抓手，不是萬用截圖機。白板 / 軟體 demo / 講者頭像 / Prezi 平滑縮放都不在範圍內。誠實標出 ✓ / 🟡 / ❌ 三類場景，使用者一眼就知道要不要用。

> 證據：演算法假設 (1) 每張投影片有可 OCR 文字，(2) 換頁是離散事件。脫離這兩個前提就要換工具，不是調參。

### V. UI 對齊使用者，不對齊工程師
Status pill 改中文（`分析投影片中` 不是 `extracting`）；技術 log 收進 `<details>`；進度條配 ETA；Job dashboard 讓使用者隨時找回背景 job。**規則**：使用者首頁看到的所有字眼，普通人要看得懂。工程術語（`cluster_jaccard`、`pHash`）藏到「技術細節」可展開區。

> 證據：用戶第一次自己跑 web GUI，55 分鐘影片的 `resolving` 階段 sync 跑 yt-dlp 沒進度回報，用戶以為卡死。下一輪改動把 yt-dlp `--newline` 進度透傳；JS poll 每 1.5s；ETA 從 polling rate 推算。

### VI. 本機運算，不洩漏資料（Local-Only by Default）
所有 OCR、聚類、PPTX 生成都在本機完成。不上傳 frame 到 cloud OCR、不上傳影片到第三方分析平台。Web GUI 預設只 bind 必要 port（本機或 Tailscale），不打外連。**鐵則**：使用者按下「開始」之前，能離線。按下之後（除非是 YouTube URL 需要下載），也能離線。

### VII. 快速失敗，錯誤訊息要可讀（Fail Fast with Clear Errors）
誤打的 local 路徑不該被丟給 yt-dlp 然後等 5 秒看 yt-dlp 報錯。`resolve_source()` 在進 pipeline 前就 raise `FileNotFoundError` 並列出兩種接受的輸入格式。每一條 raise 都告訴使用者下一步該做什麼。

### VIII. 測試 = 演算法核心 + I/O 邊界（Test the Boundaries）
不測 OCR 模型內部（無意義）、不測 EasyOCR pipeline（重）。測：
- `text_to_tokens` 的 bigram 邊界
- `classify_transition` 的 4 條規則（hard-OCR、subset、content change、growth）
- `is_url` / `resolve_source` 的輸入分派
共 14 個 unit test，每個 < 50 ms，跑完 2.4 秒。**規則**：CI 要能在 5 秒內知道演算法有沒有壞。

### IX. 小檔案、無中介層（YAGNI）
3 個入口腳本 + 1 個 review 模組 + 1 個 web wrapper。沒有抽象 framework、沒有 plugin 系統、沒有 DI container。當 `slide_web.py` 想加進度條時，新增 `JobProgressHandler` 50 行掛上 Python logging，**不**重構整個 pipeline。

### X. 推 GitHub 一律要明示授權（Owner-First Git）
這個 repo 對外是 `liaw-boy`，不是 global user。push 必須走 local config，永遠不動 global。任何 commit + push 動作都要當面確認，不主動推。

> 證據：用戶 GitHub 上有 AI / PUA 相關內容，git config 是 sgeric910601，對外身份切換只在 local repo config，永遠不修 global。

## 治理

### 修改流程
- 修改原則前必須先在 issue 或 PR description 提出，含「為什麼這條失效」+「新原則的具體場景」。
- 任何單一原則被推翻或新增，版本號跳 minor（1.0.0 → 1.1.0）。
- 整批原則重寫跳 major。

### 與其他文件的關係
- `README.md` 必須與本憲章一致（Scope / Copyright 段落）。
- 任何 agent 上下文檔（若有）必須引用本憲章，不重複內容。
- 違反憲章的 PR 自動拒收，不論 commit message 寫什麼。

### 衝突解決
本憲章 > 任何 issue 討論 > 任何外部 best practice。若三者衝突，以憲章為準；要改才能允許 PR。

---
**版本**：1.0.0 · **建立日**：2026-05-17 · **最後修改**：2026-05-17
