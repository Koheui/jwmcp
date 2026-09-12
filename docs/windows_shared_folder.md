# 00_JwMCP — Windows（Antigravity）で jwmcp を動かす

このフォルダ構成:

```
00_JwMCP/
  jwmcp/        プログラム本体（GitHub Koheui/jwmcp と同じ内容。Mac 側から更新して同期）
  home/         設定・図面データ（profiles/ に自社プロファイル futurestudio.json、drawings/ に作図データ）
  exchange/     Jw_cad との受け渡し（inbox / outbox / gaihen の .bat）
```

`home` と `exchange` は Mac と Windows の両方から同じものを見ます。Mac の Claude で作った図面や設定が Windows 側にそのまま出ます。

## Windows での初回セットアップ（1 回だけ）

1. Python 3.11 以上を入れる（https://www.python.org/downloads/windows/ 。インストーラで **Add python.exe to PATH** にチェック）
2. Google Drive for desktop でこのフォルダが見える状態にする（例: `G:\マイドライブ\_Project\00_JwMCP`）
3. `jwmcp\scripts\windows\setup.bat` をダブルクリック
   - 仮想環境は `%LOCALAPPDATA%\jwmcp\venv` に作られます（Drive の同期対象にしないため）
   - `home` と `exchange` を自動で使うよう環境変数（JWMCP_HOME / JWMCP_EXCHANGE）を設定します
   - `exchange\gaihen\` に Jw_cad 用の .bat（JWMCP_send / JWMCP_send_all / JWMCP_import）を作ります
   - 最後に Antigravity 用の MCP 設定 JSON を表示します

## Antigravity に登録する

Antigravity のエージェントパネルで MCP サーバーの管理画面（Manage MCP servers → View raw config）を開き、
setup.bat が最後に表示した JSON を `mcpServers` に追加します。形はこれです（パスは setup.bat の表示をそのまま使う）:

```json
{
  "mcpServers": {
    "jwmcp": {
      "command": "C:\\Users\\<ユーザー名>\\AppData\\Local\\jwmcp\\venv\\Scripts\\python.exe",
      "args": ["-m", "jwmcp"],
      "env": {
        "JWMCP_HOME": "G:\\マイドライブ\\_Project\\00_JwMCP\\home",
        "JWMCP_EXCHANGE": "G:\\マイドライブ\\_Project\\00_JwMCP\\exchange"
      }
    }
  }
}
```

登録後、エージェントに「jwmcp のツールを使って ~/Desktop/xxx.jww を開いて」などと頼めば動きます。

## Jw_cad との連携

- Jw_cad の **外部変形** コマンドで `exchange\gaihen\JWMCP_send.bat` を選ぶ → 範囲選択 → AI に届く → 応答が図面に入る
- `JWMCP_import.bat` は AI が用意した図形を取り込む（取り込み位置を 1 点クリック）
- DXF で受け取る場合は「ファイル > 開く」でファイルの種類を DXF にする

## 設定画面

`jwmcp\scripts\windows\settings.bat` → ブラウザで http://127.0.0.1:8765 。プロファイル（レイヤ構成・図面枠・線色・文字種）と図面ごとの設定を編集できます。

## 更新

Mac 側で `00_JwMCP/jwmcp` を上書きすれば同期されます。プログラムを更新したあとは `setup.bat` をもう一度実行してください（依存の更新と再登録のため）。

## 未検証（最初の 1 回で確認したいこと）

1. setup.bat が最後まで通る（エラーが出たら画面の文面をそのまま Claude に貼る）
2. Jw_cad の外部変形一覧に JWMCP_send.bat が出て、範囲選択後に応答が図面に入る
3. DXF を開いたときのレイヤ名・線色・文字サイズ
