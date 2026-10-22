# GenTest

設計書とコードからテスト仕様書・単体テストスクリプトを LLM（Gemini）で生成し、実行して、品質をエビデンス付きで評価するモックプロジェクト。

想定シナリオ：顧客から単体テスト自動化の依頼を受け、サンプル設計書とコードを受領 → テスト仕様書の生成、テストスクリプトの設計・実行。

## 構成

| パス | 内容 |
|---|---|
| `target/jpholiday/` | テスト対象（OSS の jpholiday を固定コミットで取り込み） |
| `baseline_tests/` | jpholiday の既存テスト（人が書いたテスト。比較用で LLM には渡さない） |
| `docs/design/` | 詳細設計書（祝日法・内閣府の公開情報から書き起こす） |
| `checklists/` | テスト観点チェックリスト |
| `bugs/` | 仕込みバグ |
| `src/gentest/` | 生成・検証・実行のパイプライン |
| `tests/` | パイプラインのテスト（LLM を呼ばない部分） |
| `notes/decision_log.md` | 判断の記録 |

## セットアップ

```sh
uv sync
cp .env.example .env   # GCP プロジェクトIDなどを設定
uv run pytest          # 既存テスト（baseline_tests）を実行
```

## テスト対象について

`target/` 配下は [Lalcs/jpholiday](https://github.com/Lalcs/jpholiday)（MIT License）のコミット `9cc718b` を取り込んだもの。ライセンスは [target/LICENSE](target/LICENSE)、既存テスト `baseline_tests/` も同リポジトリの `tests/` に由来する。
