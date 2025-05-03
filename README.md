# 介護施設シフト自動生成スクリプト

このスクリプトは、指定された従業員情報と制約に基づいて、介護施設のシフト表を自動生成します。
OR-Tools ライブラリを使用して、制約充足問題を解いています。

## 必要なもの

*   Python 3.8 以降
*   必要なライブラリ (pandas, holidays, ortools)

## セットアップ

1.  リポジトリをクローンまたはダウンロードします。
2.  ターミナルを開き、プロジェクトのルートディレクトリに移動します。
3.  仮想環境を作成して有効化します (推奨)。
    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS/Linux
    # source venv/bin/activate
    ```
4.  必要なライブラリをインストールします。
    ```bash
    pip install -r requirements.txt
    ```

## 使い方

1.  `tmp` ディレクトリに以下のCSVファイルを配置します。
    *   `シフト作成用_職員情報_v01.csv`: 従業員リストと希望休、制約など。
    *   `介護_直前3日の勤務表.csv`: シフト開始前の3日間の勤務実績。
2.  プロジェクトのルートディレクトリで以下のコマンドを実行します。
    ```bash
    python shift_generator.py
    ```
3.  生成されたシフト表は `results` ディレクトリに `shift_YYYYMMDD_vXX.csv` という名前で保存されます。

## ファイル構成

*   `shift_generator.py`: メイン実行スクリプト。
*   `requirements.txt`: 依存ライブラリ。
*   `README.md`: このファイル。
*   `src/`: ソースコードモジュール。
    *   `constants.py`: 定数定義。
    *   `data_loader.py`: データ読み込みと前処理。
    *   `utils.py`: ユーティリティ関数。
    *   `shift_model.py`: OR-Toolsモデル構築。
    *   `solver.py`: ソルバー実行。
    *   `output_processor.py`: 結果処理とCSV出力。
*   `prompts/`: プロンプトファイル (現在は未使用)。
*   `tmp/`: 入力データ用ディレクトリ。
*   `results/`: 出力結果用ディレクトリ。 