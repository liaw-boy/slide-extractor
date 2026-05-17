# Feature Specification: Extract Complete Slides from Lecture Videos

**Feature Branch**: `001-extract-slides`
**Created**: 2026-05-17
**Status**: Shipped (retroactively spec'd)
**Input**: 反向萃取自實際使用軌跡（OWASP M1 / M2 / Crypto / t4hNkGJOWnk）

---

## User Scenarios & Testing

### User Story 1 — 自動抓出完整投影片成 PPTX (Priority: P1)

**Persona**：學生 / 上班族，每週要看 3-5 部老師上傳的 YouTube 講演影片。手抄筆記效率低，需要把投影片獨立出來複習。

**User journey**：
1. 開 web GUI 首頁
2. 貼一個 YouTube URL 或本機影片路徑
3. 選 Auto 模式
4. 看進度條（下載 → OCR → 聚類 → PPTX）
5. 完成後下載 `.pptx`，每張 slide 一頁

**Why this priority**：這是核心抓手，沒有這個其他都不成立。

**Independent Test**：給一個 30-60 分鐘的講演影片 URL，10-15 分鐘內收到 PPTX，slide 數量 ±1 等於原講演實際翻頁次數。

**Acceptance Scenarios**：
1. **Given** YouTube URL of typed-slide lecture, **When** click Start in Auto mode, **Then** receive PPTX with ≥ 95% of actual slides within ETA shown.
2. **Given** local `.mp4` of lecture, **When** click Start, **Then** same outcome without re-downloading.
3. **Given** invalid local path, **When** click Start, **Then** clear error message within 1 second, not 5-second yt-dlp timeout.

---

### User Story 2 — 人工 Review 模式保證 100% 不漏頁 (Priority: P1)

**Persona**：要交報告 / 做簡報摘要 / 給老闆看的場景。漏一頁 = 整份重做。

**User journey**：
1. 同 P1 第 1-3 步，但選 Review 模式（denser sampling + lower threshold）
2. 進度跑完跳到 contact sheet（dark theme 縮圖牆）
3. 把多餘的候選勾掉（動畫漸進顯示的重複版本）
4. 按「Save selection → generate PPTX」
5. 下載 `*_REVIEWED.pptx`

**Why this priority**：演算法不能自證沒漏頁，Review 是真實 SLA。

**Independent Test**：給一個會困住 Auto 模式的影片（同模板、漸進動畫多），Review 模式 over-extract 候選；人工 30 秒勾選後產出 PPTX 與原講演 1:1 對得起來。

**Acceptance Scenarios**：
1. **Given** Auto 抓出 N 張的影片, **When** 改用 Review 模式, **Then** 候選數 > N，且能在 contact sheet 一鍵全選 / 全反選 / 局部勾選。
2. **Given** 勾選 K 張候選, **When** 按 Save, **Then** 產出 PPTX 剛好 K 頁，順序與時間軸一致。
3. **Given** Review 模式產出 PPTX, **When** 對照原影片人工計數, **Then** **0 漏頁**。

---

### User Story 3 — 並行多 job + 隨時找回背景工作 (Priority: P2)

**Persona**：批次處理一整週講演的使用者，貼完一個 URL 就想貼下一個。

**User journey**：
1. 開首頁，貼影片 #1，按開始 → 跳到 progress 頁
2. 按「← 抓另一個影片」回首頁
3. 貼影片 #2，按開始
4. 首頁 Jobs Dashboard 顯示 2 個正在跑的 job + 進度
5. 點任何 job 卡片回到該 job 的進度頁

**Why this priority**：不做這個會逼使用者開多個瀏覽器分頁，背景 job 跑完了也不知道。

**Independent Test**：開 3 個影片 job 後，首頁 dashboard 看得到 3 個 job + 個別 status / 進度 / 點擊跳轉。

**Acceptance Scenarios**：
1. **Given** 至少 1 個 job 存在, **When** 訪問首頁, **Then** 看到 Jobs Dashboard 區塊，每張卡片顯示來源 / 狀態 / 進度條。
2. **Given** job 正在跑, **When** dashboard 自動 refresh, **Then** 進度條每 2 秒更新一次，不需手動 F5。
3. **Given** 點擊 dashboard 上的 job 卡片, **When** 跳轉, **Then** 進入該 job 的 progress 頁，仍能看到完整 log + 操作按鈕。

---

### User Story 4 — 看到清楚進度 + ETA，不會以為卡死 (Priority: P2)

**Persona**：第一次跑工具的使用者，看到 `resolving` 卡 2 分鐘會懷疑出問題。

**User journey**：
1. 提交 job 後跳到 progress 頁
2. 看到大進度條 + 階段標籤（「下載影片中」「OCR 採樣」「聚類分析中」「生成 PPTX」）
3. 進度條一直在動，ETA 顯示「預估剩 4 分鐘」
4. 完成時跳出「下載 PPTX」「看候選」按鈕

**Why this priority**：UX 第一印象，沒有這個會以為工具壞掉。

**Independent Test**：跑 55 分鐘影片，progress 頁每秒看得到進度位移，全程沒有「靜止超過 5 秒」的時段。

**Acceptance Scenarios**：
1. **Given** yt-dlp 下載中, **When** 進度頁 polling, **Then** 進度條每 1-2 秒更新 % + 階段標籤 = `下載影片中`。
2. **Given** OCR 採樣中, **When** 每 50 frame 一個 batch, **Then** 進度條從 X% → X+5% 等比例增長，ETA 重算。
3. **Given** 完成, **When** status pill 變 `完成`, **Then** 出現綠色 100% bar + 兩顆按鈕。

---

### User Story 5 — 著作權保護機制清楚 (Priority: P3)

**Persona**：把工具分享出去的人 / 在公司使用前要過法務的人。

**User journey**：
1. 打開首頁、README、CLI `--help`
2. 任何一個入口都看得到「個人學習用途」+ Do / Don't 清單
3. NOTICE 檔可以單獨給法務看

**Why this priority**：合規責任要明確劃線。不做不會崩，但會出社會風險。

**Independent Test**：4 個入口（首頁、README、CLI --help、NOTICE 檔）的著作權聲明文字一致、Do/Don't 規則完全對齊。

**Acceptance Scenarios**：
1. **Given** Web UI 首頁, **When** 載入, **Then** 看到黃色 callout 框含 ⚠ 著作權聲明 + 三條 Do not。
2. **Given** GitHub repo README, **When** 訪問, **Then** 頂端 IMPORTANT 提示 + Copyright 段落 + 連到 NOTICE。
3. **Given** `python3 slide_extractor.py --help`, **When** 執行, **Then** 描述段含 Scope + Copyright 兩段。

---

## Functional Requirements

### FR-001 — Input dispatch
工具必須在 < 100ms 內判斷輸入是 URL（http/https/www. 開頭）或本機路徑。本機路徑不存在 → `FileNotFoundError` 含「兩種接受格式」說明。URL 才送 yt-dlp。

### FR-002 — Slide segmentation
給定影片，採樣間隔預設 3.0s（Auto）/ 2.0s（Review），對每個 frame 做：(a) GPU EasyOCR (ch_tra + en)，(b) pHash。用 token bigram + jaccard 做 online clustering，cluster threshold 預設 0.45 / 0.30。每個 cluster 取 token 數最多的 frame 當代表（= 動畫完成的 frame）。

### FR-003 — Output formats
每個 slide 寫成 `slide_NNN_HHhMMmSSs.png`；PPTX 頁面尺寸從第一張 slide 推導比例（保留 source aspect ratio，**不**強制 16:9）。

### FR-004 — Web GUI single page
單一 page 接受 URL 或本機路徑 + 模式選擇。提交後 redirect 到 `/job/<id>` progress 頁；完成後顯示按鈕（下載 PPTX / 看候選）。

### FR-005 — Live progress
進度頁每 1.5s polling `/api/job/<id>` 取得 `progress_current` / `progress_total` / `progress_label`。下載階段透傳 yt-dlp `--newline` 進度，extraction 階段 parse `LOG` records（"sampled N valid frames"）。

### FR-006 — Jobs dashboard
首頁列出所有 job（in-memory）含 source / status / 進度 / 建立時間。每 2 秒自動 refresh。點卡片跳轉 `/job/<id>`。

### FR-007 — Non-ASCII filenames in HTTP
下載 PPTX 時 `Content-Disposition` 須用 RFC 5987 `filename*=UTF-8''…` 處理中文檔名。fallback `filename=` 用 ASCII 替換版。

### FR-008 — Local-only by default
所有處理在本機。yt-dlp 為唯一外連（且只有 URL 模式才觸發）。bind 預設 `0.0.0.0`（Tailscale 用）— 文件提醒可改 `127.0.0.1` 只開本機。

---

## Out of Scope

- 影片下載功能本身的合法性審查（責任歸使用者）
- 非投影片型內容的識別（白板、demo、talking-head）— 列適用範圍但不解
- 跨講演關聯（連續課程的章節合併）
- 雲端版（會違反「本機運算」原則）
- 多語言 OCR 自動偵測（手動 `--lang` 即可）
- mobile-native 介面（web GUI 在手機瀏覽器已可用）

---

## Open Questions

1. 演算法該不該預設修 cluster_jaccard 0.45 → 0.35 來自動合併 intro/full 動畫？需要回歸測試 3-4 部影片才能動。
2. 該不該把 progress 頁的「技術 log」改成預設展開（給工程師）vs 收起（給一般使用者）？目前收起。
3. PyInstaller 打包要不要做？檔案大（300-500MB 含 EasyOCR 模型），但雙擊體驗最簡單。
4. 是否要支援多人並行使用同一個 web server（目前 jobs in-memory 全域共享，沒帳號隔離）？
