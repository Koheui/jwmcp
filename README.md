# jwmcp — Jw_cad を AI から駆動する MCP サーバー

[English below](#english)

Jw_cad（日本で広く使われるフリーの 2D CAD）には外部 API がありません。jwmcp は Claude などの AI エージェントが
Jw_cad の図面を **読み**、**描き**、**Jw_cad に戻す** ための [MCP](https://modelcontextprotocol.io) サーバーです。
スキャン図面や PDF から、壁厚・建具サイズを指定してレイヤ分けされた CAD を起こす流れまでを一式で扱います。

| 経路 | 内容 | 状態 |
| --- | --- | --- |
| **.jww 読取** | [ezjww](https://github.com/monozukuri-ai/ezjww)（MIT）で解析し実寸 mm に正規化。PNG で AI が図面を見る | 実物 .jww で確認済 |
| **作図** | 壁（芯線＋壁厚）、建具（幅・種類・開き勝手）、通り芯、柱、室名、配管、機器を Jw_cad の線・円弧・文字に展開 | 実装済 |
| **出力** | DXF（Jw_cad で直接開ける）／外部変形テキスト（レイヤ・線色・線種付き） | DXF は ezdxf で検証済。Jw_cad 実機取込は未 |
| **外部変形ブリッジ** | 生成した `.bat` を Jw_cad の外部変形から実行。選択図形が共有フォルダ経由で AI に届き、応答が図面に反映 | 実装済。Windows 実機は未検証 |
| **スキャン/PDF → CAD** | ページ化・拡大閲覧・実寸校正・原図への重ね合わせ照合。ベクター PDF は線をそのまま取込 | 実装済 |

`.jww` の**直接書き出し**（MFC CArchive の再現）は未着手。往復は DXF か外部変形で行います。

## セットアップ

```bash
git clone <this repo> jwmcp && cd jwmcp
uv venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
python -m pytest -q
```

Claude Code に登録:

```bash
claude mcp add jwmcp -- /path/to/jwmcp/.venv/bin/python -m jwmcp
```

Claude Desktop / Antigravity など他の MCP クライアントも同様に stdio で `python -m jwmcp` を登録します。

環境変数:

- `JWMCP_HOME` — 作図データ・スキャン・プレビュー・エクスポートの保存先（既定 `~/.jwmcp`）
- `JWMCP_EXCHANGE` — 外部変形ブリッジの共有フォルダ（既定 `~/JW_MCP_Exchange`）。Google Drive 等の同期フォルダにすると Windows 側と共有できる

## Windows で動かす（Jw_cad と同じ PC）

依存パッケージはすべて Windows x64 用のホイールがあり、Mac と同じコードがそのまま動きます。

1. Python 3.11 以上を入れる（インストーラで "Add python.exe to PATH" にチェック）
2. リポジトリを取得して `scripts\windows\setup.bat` をダブルクリック
   （`.venv` 作成 → インストール → テスト → 外部変形用フォルダ `%USERPROFILE%\JW_MCP_Exchange` と .bat 生成 → `claude` CLI があれば MCP 登録）
3. Claude Desktop を使う場合は `claude_desktop_config.json` に次を追加

```json
{"mcpServers": {"jwmcp": {"command": "C:\\path\\to\\jwmcp\\.venv\\Scripts\\python.exe", "args": ["-m", "jwmcp"]}}}
```

4. 設定画面は `scripts\windows\settings.bat`
5. Jw_cad 側は `JW_MCP_Exchange\gaihen\JWMCP_send.bat` などを外部変形から選ぶだけ。同じ PC なので共有フォルダの同期は不要

DXF を Jw_cad で開くときの約束: DXF には縮尺情報が無く座標は実寸 mm なので、
基本設定「DXF・SXF・JWC」の **「図面範囲を読取る」を OFF** にし、新規図面で **用紙と縮尺を出力時の値（例: A3・1/50）に合わせてから** 開く。
ON のままだと Jw_cad が現在の用紙サイズから縮尺を推定し、意図しない用紙・縮尺になる。

Mac に Claude、Windows に Jw_cad という分担でも動きます。その場合は `JWMCP_EXCHANGE` を Google Drive 等の同期フォルダにし、
`gaihen_setup(win_exchange="G:\\マイドライブ\\JW_MCP_Exchange")` のように Windows 側から見たパスを渡して .bat を作ります。

## 使い方の例

```
「~/Desktop/plan.jww を開いて、室名を一覧にして」          → jww_info / jww_texts / jww_preview
「1/100、A3、既存図プリセットで新しい図面を作って」          → drawing_new(preset="arch_jp_renovation")
「X1〜X4=3640ピッチ、Y1〜Y3=4550ピッチの通り芯」            → drawing_add(grid)
「X2通りに厚90の間仕切り、始点から1000に幅800の片開き戸」   → drawing_add(wall + openings)
「プレビューして」「DXFで出して」                            → drawing_preview / drawing_export
「このPDFをCAD化して」                                       → scan_open → scan_view → scan_calibrate → drawing_add → scan_overlay
```

## ツール一覧

### .jww 読取
`jww_info` `jww_query` `jww_texts` `jww_preview` `jww_to_dxf`

### 作図
`drawing_new(name, scale, paper, preset?)` `drawing_add(name, entities)` `drawing_entities` `drawing_update` `drawing_remove`
`drawing_layers` `drawing_info` `drawing_list` `drawing_import_jww` `drawing_preview` `drawing_export(dxf|jwc_temp|json)` `presets_list`

`entities` は JSON の配列。基本図形（line / polyline / rect / circle / arc / text / point / dimension / solid）に加えて建築部品:

| type | 主なキー | 展開結果 |
| --- | --- | --- |
| `wall` | `points`（芯線）, `thickness`, `closed`, `core`（壁芯を一点鎖線で）, `openings[{at,width,kind,hinge,side,frame}]` | 両面線・端部・建具（片開き/両開き/引違い/窓/FIX/開口）の記号 |
| `grid` | `xs`, `ys`, `x_labels`, `y_labels`, `extend`, `dims` | 通り芯（一点鎖線）＋符号バブル＋（任意）寸法 |
| `column` | `cx`, `cy`, `w`, `h`, `angle`, `hatch` | 柱矩形＋対角線 |
| `room` | `x`, `y`, `name`, `note` | 室名・注記 |
| `pipe` | `points`, `system`（給水/給湯/排水/通気/ガス/冷媒/ドレン/ダクト/給気/排気）, `diameter` | 系統別の線色・線種＋口径ラベル |
| `equipment` | `kind`（toilet/sink/washbasin/bath/kitchen/ac_indoor/ac_outdoor/fan/cubicle/tank/elevator/box）, `x`, `y`, `w`, `h`, `angle`, `label` | 機器記号＋ラベル |

プリセット（`presets_list`）: `arch_jp`（一般平面図）, `arch_jp_renovation`（既存図。0敷地 1記述 2躯体 3建具 4内部壁 5計画図）, `mep_jp`（設備図）。
プリセット付きの図面では、部品の種類ごとにレイヤグループ・レイヤ・線色が自動で入ります。

### 設定画面（ブラウザ）

```bash
python -m jwmcp settings        # http://127.0.0.1:8765 が開く
```

会社や案件ごとのプロファイル（レイヤグループ・レイヤ名・縮尺・部品の既定・線色・文字種・図面枠）を画面で編集できます。
`jw_win.jwf` やテンプレート `.jww` をドラッグ＆ドロップすると値が自動で入り、図面枠は用紙サイズを切り替えてプレビューできます。
「図面ごとの設定」タブでは個々の図面のレイヤ構成を編集し、プロファイルを適用したり、逆に図面の構成を新しいプロファイルとして保存できます。
プロファイルは JSON 1 ファイルなので、そのまま他の人に渡せます。

### プロファイル（会社設定）と図面枠
`profile_list` `profile_show` `profile_set` `profile_from_jwf(path, name)` `profile_from_jww(path, name, frame_lg?)` `jwf_read` `drawing_frame`

レイヤグループ名・レイヤ名・縮尺・部品ごとの既定レイヤ・線色・文字種・図面枠を **1 つの JSON**（`$JWMCP_HOME/profiles/<name>.json`）にまとめ、
`drawing_new(profile="...", frame=true, fields={...})` で新規図面に一括適用します。

- `.jwf`（Jw_cad 環境設定）から線色 RGB・印刷線幅・文字種 1〜10 の寸法・フォント・既定縮尺を取り込む
- 既存の `.jww` からレイヤグループの縮尺・名前を学習し、`frame_lg` を指定するとそのグループを **図面枠テンプレート**として取り込む
  （図寸 mm に変換して保存。A4〜A1 どの用紙でも S=1:1 のグループに配置し、横方向は用紙幅に合わせて伸縮、下端からの距離は維持）
- テンプレートが無ければ内蔵の表題帯（No. / Title / Drawing / Scale / Note / ロゴ）を用紙サイズに合わせて生成
- 図面枠は専用レイヤグループ（既定 F）を 1/1 にして置く。DXF 出力とプレビューでは主縮尺に合わせて自動で拡大し、
  外部変形テキストではグループごとの実寸のまま出す（Jw_cad 側でグループ F を 1/1 にしておく）

### 外部変形ブリッジ
`gaihen_setup(exchange?, win_exchange?, wait)` `gaihen_status` `gaihen_jobs` `gaihen_read` `gaihen_preview`
`gaihen_respond(job_id, entities | drawing, delete_selected?, notice?)` `gaihen_cancel` `gaihen_prepare_import` `jwc_temp_parse`

### スキャン / PDF → CAD
`scan_open(path)` `scan_list` `scan_view(scan_id, region)` `scan_calibrate(p1,p2,distance_mm | scale)` `scan_px_to_mm`
`scan_overlay(scan_id, drawing)` `scan_vector_import(scan_id, drawing)` `scan_texts`

流れ: 開く → 拡大して読む（ピクセル定規付き）→ 既知寸法か縮尺で実寸校正 → 壁・建具・通り芯を部品として置く → 原図に重ねて照合 → DXF / 外部変形で Jw_cad へ。

## 座標と属性の約束

- 座標は常に **実寸 mm**。1/100 図面の 3,640 mm の壁は `3640`。
- 文字の高さ・幅・間隔だけは Jw_cad と同じ **図寸 mm**。
- `lg` レイヤグループ 0–15、`ly` レイヤ 0–15（16 進 "A"–"F" も可）、`lc` 線色 1–9、`lt` 線種 1–9（1 実線 2 点線1 3 点線2 4 点線3 5 一点鎖1 6 一点鎖2 7 二点鎖1 8 二点鎖2 9 補助線種）。

## 外部変形ブリッジの流れ

```
Jw_cad(Windows)                     共有フォルダ                     MCP サーバー
  外部変形 > JWMCP_send.bat ──▶ inbox/<job>.txt ──────────────▶ gaihen_jobs / gaihen_read
  (JWC_TEMP.TXT を hq のみに)                                       AI が図形を生成
  応答を待つ ◀──────────────── outbox/<job>.txt ◀────────────── gaihen_respond
  JWC_TEMP.TXT に戻して反映
```

タイムアウト時は JWC_TEMP.TXT が `hq` のままなので Jw_cad は「未実行」と表示し何も変えません。

## ライセンス

MIT。依存: ezjww (MIT), ezdxf (MIT), matplotlib (PSF), pdfplumber (MIT), pypdfium2 (Apache-2.0 / BSD-3), Pillow (MIT-CMU), mcp (MIT)。
Jw_cad 本体のコードは含みません。LibreCAD jwwlib（GPL）のコードも使っていません。Jw_cad は清水治郎氏・田中善文氏の著作物です。

---

## English

**jwmcp** is an MCP server that lets AI agents (Claude, etc.) work with [Jw_cad](https://www.jwcad.net/), the free 2D CAD
widely used in Japan. Jw_cad has no external API; jwmcp bridges that gap:

- **Read `.jww`** files (via ezjww), normalise to real millimetres, render PNG previews so the model can *see* the drawing.
- **Draw** with architectural elements — walls (centre line + thickness), openings (door / double door / sliding / window / fixed),
  grids with bubbles, columns, room labels, piping systems, equipment symbols — expanded to Jw_cad lines/arcs/text with layer
  group / layer / pen colour / line type.
- **Export** DXF (opens directly in Jw_cad) or the 外部変形 `JWC_TEMP.TXT` format with full Jw_cad attributes.
- **Round-trip with a running Jw_cad** through generated 外部変形 batch files and a shared folder (works across Mac ↔ Windows
  via Google Drive etc.). A timeout leaves the drawing untouched.
- **Scan / PDF → CAD**: page rendering, zoomed views with a pixel ruler, mm calibration, overlay check, and direct vector
  import from CAD-exported PDFs.

Coordinates are always real mm; text sizes are paper mm like Jw_cad's 文字種. Writing native `.jww` (MFC CArchive) is not
implemented yet — use DXF or the 外部変形 bridge.

```bash
uv venv .venv && source .venv/bin/activate && uv pip install -e ".[dev]" && python -m pytest -q
claude mcp add jwmcp -- /path/to/.venv/bin/python -m jwmcp
```

MIT licensed. Jw_cad is the work of Jiro Shimizu and Yoshifumi Tanaka; this project contains none of its code.
