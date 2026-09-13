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

## 会社設定＝プロファイル（2026-09-12）
- レイヤグループ・レイヤ名・縮尺・部品ごとの既定・線色・文字種・図面枠は `~/.jwmcp/profiles/<name>.json` に集約。
  `profile_from_jwf`（jw_win.JWF）＋ `profile_from_jww(frame_lg=…)`（既存図面から枠を学習）＋ `profile_set` で作る。
- 図面枠は専用グループ（既定 F）を **1/1** にして置く。DXF・プレビューは主縮尺に合わせて枠を拡大（`Drawing.unified_entities`）、
  外部変形テキストはグループ別実寸のまま（Jw_cad 側テンプレートでグループ F を 1/1 に）。
- 浩平さんの自社枠（KDICリニューアルプラン_2.jww のグループ0）は「下端の表題帯（No./Title/Drawing/Scale/Note/ロゴ）」。
  テンプレート取り込み時は元図の値文字と `^@BM` 画像参照を落とし、ラベル位置からセルを推定して値を差し込む。
- 外部変形の座標は「基準点相対」。send 系 .bat は `#hp`（基準点＝用紙左下）＋`#zs` で用紙サイズを得て図面原点（用紙中心）に換算する。
  import.bat は `#0` で取り込み位置を 1 点指示させる。

## .jwf の読み方で間違えやすい所（2026-09-13 公式ヘルプ Jw_cad.chm と Sample.jwf で確認）
- `PCOLLOR_n = r g b 線幅 実点半径`。5 番目は線幅ではなく実点半径。線幅の単位は `S_COMM_2` の 2 番目で決まり、
  正なら dot、負なら 1/N mm（田村さんの環境は -100 で 1/100 mm）。
- `LTYPE_02..08 = hex 1パターンのドット数 画面ピッチ 印刷ピッチ`、`LTYPE_09` は印刷ピッチなし、
  `LTYPE_R1..R5 = hex 画面振幅 画面ピッチ 印刷振幅 印刷ピッチ`、`LTYPE_L1..L4` は倍長線種で通常と同じ並び。
  hex は 32 ビット、上位ビットが 1 文字目（「－」=描く、空白=描かない）。
- `P_dpi`（300/600）は Jw_cad が読むが .jwf に書き出さない。点線ピッチがこの dpi 基準で印刷されるかはヘルプに記載がない。
  推測で断定せず、`linetype_test_sheet` を実機で印刷して確かめる前提にしている。

## 環境
- Python 3.11 venv（`.venv`）。mcp SDK は **2.x**（`from mcp.server.mcpserver import MCPServer, Image`）。
  画像を返すツールは `structured_output=False` が必要。
- テスト: `python -m pytest -q`（実物 .jww は ~/Desktop/jww, ~/Desktop/Studio にある）。
- Mac に Wine / Jw_cad は無い。Windows 実機（kabu 自動売買のミニ PC など）と Google Drive 共有で外部変形ブリッジを使う想定。

## 未検証（Windows 実機が要る）
- 生成した .bat が Jw_cad の外部変形一覧に出て、inbox/outbox 往復が動くこと。
- 出力した JWC_TEMP.TXT / DXF を Jw_cad が想定どおり読むこと（特に文字の cn0 行と寸法の cs）。
