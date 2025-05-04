# アプリケーションアーキテクチャ概要

このドキュメントは、シフト生成アプリケーションの主要なPythonモジュールとその役割、データの流れを概説します。

## モジュール構成 (`src/` ディレクトリ内)

1.  **`constants.py`**
    *   **役割:** アプリケーション全体で使用される定数を定義します。
    *   **主な内容:** 入力/出力ファイルのパス (`input/`, `results/`), シフト期間設定, シフト記号と整数IDのマッピング, 人員配置基準 (実験用), 制約のデフォルト値など。
    *   **依存関係:** 他の多くのモジュールからインポートされます。

2.  **`utils.py`**
    *   **役割:** プロジェクト全体で再利用可能な汎用ユーティリティ関数を提供します。
    *   **主な内容:** 日付範囲の生成 (`get_date_range`), 祝日リストの取得 (`get_holidays`), 従業員情報へのアクセス補助関数 (`get_employee_indices`, `get_employee_info`) など。
    *   **依存関係:** `data_loader.py`, `output_processor.py`, `shift_model.py` などから利用される可能性があります。

3.  **`data_loader.py`**
    *   **役割:** **外部データソース（CSVファイル）から基本的なデータを読み込む**ことに責任を持ちます。ルールの解釈は行いません。
    *   **主な内容:**
        *   従業員基本情報 (`input/employees.csv`) の読み込み (`load_employee_data`)。
        *   過去勤務実績 (`input/past_shifts.csv`) の読み込み (`load_past_shifts`)。
        *   自然言語ルール (`input/rules.csv`) の読み込み (`load_natural_language_rules`)。(★現在はシミュレーションのため未使用だが、将来のAI連携で使用)
    *   **依存関係:** `constants.py`, `utils.py` を利用。メインスクリプト (`shift_generator.py`) から呼び出される。

4.  **`rule_parser.py`**
    *   **役割:** **AIによって整形された「定型文ルール」**（現在は `shift_generator.py` でシミュレート）を入力とし、それを解析してOR-Toolsモデルが直接利用できる**「構造化ルールデータ」（Python辞書のリスト）に変換する**ことに責任を持ちます。
    *   **主な内容:** `parse_structured_rules_from_ai` 関数。定型文ごとの正規表現や文字列処理によるパラメータ抽出ロジック。基本的なデータ検証。
    *   **依存関係:** `constants.py` を利用。メインスクリプト (`shift_generator.py`) から呼び出され、その結果が `shift_model.py` に渡される。

5.  **`shift_model.py`**
    *   **役割:** OR-Tools CP-SATモデルの構築、**構造化されたルールデータ（パーサー経由）と基本従業員情報（データローダー経由）に基づいて制約と目的関数をモデルに追加する**ことに責任を持ちます。
    *   **主な内容:** `build_shift_model` 関数。OR-Tools変数の定義、構造化ルールに応じた制約追加、全体ルール（人員配置、夜勤ローテなど）の制約追加、ソフト制約のペナルティ変数定義、目的関数 (`model.Minimize()`) の設定。
    *   **依存関係:** `constants.py`, `utils.py` を利用。メインスクリプトから呼び出され、構造化ルールデータと基本データを受け取る。

6.  **`solver.py`**
    *   **役割:** 構築されたOR-Toolsモデルを入力とし、**ソルバーを実行して解を求める**ことに責任を持ちます。
    *   **主な内容:** `solve_shift_model` 関数。`CpSolver` のインスタンス化、パラメータ設定（タイムリミットなど）、`Solve()` メソッドの呼び出し、結果ステータスとソルバーオブジェクトの返却。
    *   **依存関係:** メインスクリプトから呼び出され、`shift_model.py` で構築されたモデルを受け取る。

7.  **`output_processor.py`**
    *   **役割:** ソルバーが見つけた解を入力とし、**最終的なシフト表を指定されたフォーマットのDataFrameに整形し、CSVファイルとして保存する**ことに責任を持ちます。
    *   **主な内容:** 初期DataFrame作成 (`create_shift_dataframe`), ソルバー結果処理と書き込み (`process_solver_results`), 集計処理, バージョン管理付きCSV保存 (`save_shift_to_csv`)。
    *   **依存関係:** `constants.py`, `utils.py` を利用。メインスクリプトから呼び出され、ソルバーの結果や関連データを受け取る。

## データフロー（現在: AI整形シミュレーション版）

```mermaid
graph LR
    subgraph データ読み込み
        B1[input/employees.csv] --> DL(data_loader.py);
        B2[input/past_shifts.csv] --> DL;
        B3[input/rules.csv] --> DL;
    end
    subgraph メイン処理
        A[shift_generator.py];
    end
    subgraph AI処理_シミュレーション
        C[AI整形シミュレーション<br>(shift_generator.py内)];
    end
    subgraph ルール解析
        D[rule_parser.py];
    end
    subgraph モデル構築と最適化
        E[shift_model.py];
        F[solver.py];
    end
    subgraph 結果処理と出力
        G[output_processor.py];
        H[results/shift_*.csv];
    end

    DL -- 基本データ --> A;
    A -- 自然言語ルール(今回は未使用) --> C;
    C -- 整形済み定型文(シミュレート) --> A;
    A -- 整形済み定型文 --> D;
    D -- 構造化ルール --> A;
    A -- 基本データ & 構造化ルール --> E;
    E -- OR-Toolsモデル --> A;
    A -- モデル --> F;
    F -- 解(Status, Solver) --> A;
    A -- 解 & 基本データ --> G;
    G -- 最終Shift DataFrame --> A;
    A -- DataFrame --> G;
    G -- CSV保存 --> H;

```

(※上記フローは簡略化したもので、実際のデータの受け渡しは関数呼び出し経由です。) 