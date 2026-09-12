# Antigravity への指示書 — Windows で jwmcp をセットアップし、Jw_cad と接続する

この文書を Antigravity のエージェントにそのまま渡してください。上から順に実行し、最後の「報告」を返してください。

---

## あなた（エージェント）への前提

- 作業対象は Google Drive 上のフォルダ `00_JwMCP`（例: `G:\マイドライブ\_Project\00_JwMCP`。ドライブ文字は環境で異なるので最初に確認する）。
- 中身: `jwmcp\`（プログラム本体・Python 製）、`home\`（設定と図面データ）、`exchange\`（Jw_cad との受け渡し）。
- 目的: この PC の Antigravity から jwmcp の MCP ツールが使える状態にし、Jw_cad（外部変形）と往復できることを確認する。
- 守ること
  - `jwmcp\` 配下のソースコードは変更しない（問題があれば報告に書く）。
  - 仮想環境は Google Drive の中に作らない（`%LOCALAPPDATA%\jwmcp\venv` を使う）。
  - `home\` と `exchange\` の中身は削除しない。
  - 秘密情報（API キー等）の入力は不要。求められても入力しない。

---

## 手順 1: 環境確認

PowerShell または コマンドプロンプトで:

```bat
python --version
py -3 --version
where claude
```

- Python が 3.11 以上でなければ https://www.python.org/downloads/windows/ から入れる（「Add python.exe to PATH」にチェック）。インストール後にターミナルを開き直す。
- `claude` は無くてよい（Antigravity から使うため）。
- `00_JwMCP` の実パスを確認して控える（以下 `<SHARE>` と書く）。

## 手順 2: セットアップ実行

```bat
"<SHARE>\jwmcp\scripts\windows\setup.bat"
```

これが行うこと: `%LOCALAPPDATA%\jwmcp\venv` 作成 → `pip install -e jwmcp[dev]` → テスト → 環境変数 `JWMCP_HOME=<SHARE>\home` と `JWMCP_EXCHANGE=<SHARE>\exchange` を setx → `exchange\gaihen\` に Jw_cad 用 .bat を生成 → 最後に MCP 設定 JSON を表示。

期待する結果: `24 passed`（または全件 pass）、`registered` か JSON の表示。
失敗したら「手順 2b」へ。成功したら「手順 3」へ。

### 手順 2b: setup.bat が失敗したときの手動手順

```bat
py -3 -m venv "%LOCALAPPDATA%\jwmcp\venv"
"%LOCALAPPDATA%\jwmcp\venv\Scripts\python.exe" -m pip install --upgrade pip
"%LOCALAPPDATA%\jwmcp\venv\Scripts\python.exe" -m pip install -e "<SHARE>\jwmcp[dev]"
setx JWMCP_HOME "<SHARE>\home"
setx JWMCP_EXCHANGE "<SHARE>\exchange"
```

新しいターミナルを開いてから:

```bat
"%LOCALAPPDATA%\jwmcp\venv\Scripts\python.exe" -m pytest -q "<SHARE>\jwmcp\tests"
"%LOCALAPPDATA%\jwmcp\venv\Scripts\python.exe" -c "from jwmcp import bridge; print(bridge.setup())"
```

エラーが出た場合は、エラー文の全文を報告に入れる（特に `ezjww` `pypdfium2` `matplotlib` のインストールエラー、`cp932`/文字コードのエラー）。

## 手順 3: Antigravity に MCP サーバーを登録

Antigravity のエージェントパネル → MCP サーバーの管理（Manage MCP servers）→ View raw config を開き、`mcpServers` に次を追加する。
`<USER>` はこの PC のユーザー名、`<SHARE>` は手順 1 のパス（JSON ではバックスラッシュを `\\` と 2 つ書く）。

```json
{
  "mcpServers": {
    "jwmcp": {
      "command": "C:\\Users\\<USER>\\AppData\\Local\\jwmcp\\venv\\Scripts\\python.exe",
      "args": ["-m", "jwmcp"],
      "env": {
        "JWMCP_HOME": "<SHARE>\\home",
        "JWMCP_EXCHANGE": "<SHARE>\\exchange"
      }
    }
  }
}
```

保存して MCP サーバーを再読み込みし、`jwmcp` のツール一覧（`jww_info`, `drawing_new`, `gaihen_setup` など 41 個）が見えることを確認する。

## 手順 4: 動作確認（MCP ツールを実際に呼ぶ）

以下を順に実行し、結果を報告に貼る。

1. `profile_list` → `futurestudio` が見えること（`home\profiles` が読めている証拠）。
2. `drawing_list` → `FS_A3` などが見えること。
3. `drawing_new` で `name="win_test"`, `profile="futurestudio"`, `paper="A3"`, `frame=true`, `fields={"title":"Windows接続テスト","no":"01","scale":"S=1:50"}`。
4. `drawing_add` で `name="win_test"`, entities:
   ```json
   [{"type":"grid","xs":[0,3640,7280],"ys":[0,3640],"extend":1000},
    {"type":"wall","points":[[0,0],[7280,0],[7280,3640],[0,3640]],"closed":true,"thickness":150,
     "openings":[{"at":2000,"width":1800,"kind":"sliding"}]},
    {"type":"room","x":3640,"y":1820,"name":"事務室"}]
   ```
5. `drawing_preview` で `name="win_test"` → 画像が返ること（日本語が豆腐になっていないか見る）。
6. `drawing_export` で `name="win_test"`, `format="dxf"`, `out="<SHARE>\home\exports\win_test.dxf"`。
7. `gaihen_status` → `bats_present` に `JWMCP_send.bat` `JWMCP_send_all.bat` `JWMCP_import.bat` が並ぶこと。

## 手順 5: Jw_cad で確認（人が操作する部分。エージェントは手順を案内し、結果を聞き取る）

A. **DXF を開く**（DXF には縮尺情報が無いので、先に Jw_cad 側の用紙と縮尺を合わせるのが確実）
   1. Jw_cad の 設定 → 基本設定 → 「DXF・SXF・JWC」タブ → **「図面範囲を読取る」のチェックを外す** → OK
      （ON だと Jw_cad が今の用紙サイズから縮尺を勝手に計算し、A1 で 1/20 のような結果になる）
   2. ファイル → 新規。画面右下の用紙ボタンで **A-3**、縮尺ボタンで **1/50** にする（`drawing_export` の結果に書いてある paper / scale と同じにする）
   3. ファイル → 開く → ファイルの種類「DXF」→ `<SHARE>\home\exports\win_test.dxf`
   期待: A3・1/50 のまま開き、図面枠が紙の下端に収まり、7,280×3,640 の部屋の中に「事務室」。
   確認: レイヤ名（通り芯・壁・室名・図面枠）が付いているか、「事務室」「Windows接続テスト」の文字が読めるか（文字化けなら報告）。
   もし縮尺が極端（1/1000000 など）になる場合は、DXF が古い版です。Antigravity で `drawing_export` を実行し直して新しい DXF を作る。

B. **外部変形（送信）**: Jw_cad で何か図面を開き → 外部変形 → `<SHARE>\exchange\gaihen\JWMCP_send.bat` を選ぶ → 範囲選択 → 待機状態になる。
   その間に Antigravity で `gaihen_jobs` → ジョブが 1 件見えること → `gaihen_read` で図形が読めること →
   `gaihen_respond` で `job_id` と entities `[{"type":"text","x":0,"y":0,"text":"jwmcp OK","height":5}]` を返す。
   確認: Jw_cad に「jwmcp OK」の文字が入ったか。何も起きない／「未実行」と出た場合はその旨を報告。

C. **外部変形（取込）**: Antigravity で `gaihen_prepare_import` に `drawing="win_test"` → Jw_cad で外部変形 → `JWMCP_import.bat` → 取り込み位置を 1 点クリック。
   確認: 図面枠付きの平面図が入ったか。枠の位置（用紙下端）と大きさ。

D. **設定画面**: `<SHARE>\jwmcp\scripts\windows\settings.bat` を実行 → ブラウザで http://127.0.0.1:8765 が開き、プロファイル `futurestudio` が表示されること。

---

## 報告（この形式で返す）

```
■ 環境
 Windows: <版>  Python: <版>  Drive パス: <SHARE>
■ 手順2 setup.bat: 成功 / 失敗（エラー全文: ...）
■ 手順3 Antigravity 登録: ツール数 <n>
■ 手順4
 1 profile_list: ...   2 drawing_list: ...   3-4 作図: ...   5 preview: 文字OK / 豆腐
 6 DXF 出力: パス   7 gaihen_status: ...
■ 手順5
 A DXF を Jw_cad で開いた結果: 枠の位置 / レイヤ名 / 文字
 B 外部変形 送信: ジョブ検出 / 応答が図面に入ったか / 座標のずれ
 C 外部変形 取込: 結果
 D 設定画面: 開いたか
■ 気づいた問題・エラー文（そのまま貼る）
```
