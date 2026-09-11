# jwmcp — プロジェクトメモ（Claude Code 用）

Jw_cad を AI から扱う MCP サーバー。全体像と使い方は README.md。ここには判断の根拠だけ書く。

## 前提（変えない）
- **Jw_cad 専用**。他 CAD への汎用化や Cad_Cloud との共用はしない（2026-09-12 浩平さん決定）。名前に Jw を含めてよい。
- Jw_cad には外部 API が無い。拡張口は「外部変形」（Jw_cad 内でユーザーが .bat を選ぶ → JWC_TEMP.TXT 往復）だけ。
  よって「AI が能動的に Jw_cad を動かす」のではなく「ユーザーの 1 クリックで AI の結果が図面に入る」設計にしている。
- .jww の読み取りは ezjww（MIT）に任せる。LibreCAD jwwlib（GPL）のコードは使わない。
- .jww の書き出し（MFC CArchive の再現）は未着手。往復は DXF か外部変形テキストで行う。

## 座標・属性の約束
- 実寸 mm 統一。ezjww は図寸 mm を返すのでレイヤグループ縮尺を掛けている（jww_read.py）。
- 文字サイズだけ図寸 mm（Jw_cad と同じ）。文字の外部変形書式 `ch x y dx dy "文字` の (dx,dy) は
  文字列全長ベクトル（全角 1・半角 0.5 × 幅 + 間隔）。
- 外部変形の応答ファイルに `hq` を残すと Jw_cad は「未実行」扱いで何もしない。これを安全弁に使っている。

## 公開前提（2026-09-12 浩平さん決定）
- MIT で公開する。AGPL の PyMuPDF は使わない（PDF は pdfplumber + pypdfium2）。
- README は日英併記。Jw_cad 本体のコード・LibreCAD jwwlib（GPL）のコードは入れない。

## スキャン → CAD の方式
- 線をなぞる（ラスタのベクトル化）のではなく、AI が図面を読んで壁・建具・通り芯を **部品として置き直す**。
  scan_view（ピクセル定規付き）→ scan_calibrate → drawing_add(wall/grid/...) → scan_overlay で照合。
- ベクター PDF（CAD 出力）は scan_vector_import で線をそのまま取れる。pdfplumber の `path` 命令を辿ること
  （`pts` をつなぐとサブパス間の移動が線になる）。

## 環境
- Python 3.11 venv（`.venv`）。mcp SDK は **2.x**（`from mcp.server.mcpserver import MCPServer, Image`）。
  画像を返すツールは `structured_output=False` が必要。
- テスト: `python -m pytest -q`（実物 .jww は ~/Desktop/jww, ~/Desktop/Studio にある）。
- Mac に Wine / Jw_cad は無い。Windows 実機（kabu 自動売買のミニ PC など）と Google Drive 共有で外部変形ブリッジを使う想定。

## 未検証（Windows 実機が要る）
- 生成した .bat が Jw_cad の外部変形一覧に出て、inbox/outbox 往復が動くこと。
- 出力した JWC_TEMP.TXT / DXF を Jw_cad が想定どおり読むこと（特に文字の cn0 行と寸法の cs）。
