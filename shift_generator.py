# メイン実行スクリプト
import sys
import pandas as pd # 過去シフト転記で必要
from datetime import timedelta # 過去シフト転記で必要

# src ディレクトリを Python パスに追加 (環境によっては不要な場合もある)
# import os
# sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.constants import (
    EMPLOYEE_INFO_FILE, PAST_SHIFT_FILE, OUTPUT_DIR,
    START_DATE, END_DATE
)
from src.data_loader import load_employee_data, load_past_shifts, load_natural_language_rules
from src.utils import get_date_range, get_holidays, get_employee_indices
from src.shift_model import build_shift_model
from src.solver import solve_shift_model
from src.output_processor import create_shift_dataframe, process_solver_results, save_shift_to_csv
# 修正: 新しいパーサー関数をインポート
from src.rule_parser import parse_structured_rules_from_ai

def main():
    """メイン処理"""
    print("--- Shift Generator Script Start ---")

    # 1. データの読み込みと準備
    print("Loading base data...")
    employees_df = load_employee_data(EMPLOYEE_INFO_FILE)
    past_shifts_df = load_past_shifts(PAST_SHIFT_FILE, START_DATE)
    # 自然言語ルールを読み込み
    natural_language_rules = load_natural_language_rules()

    if employees_df is None:
        print("エラー: 従業員情報の読み込みに失敗しました。処理を中断します。")
        sys.exit(1)
    if not natural_language_rules: # ルール辞書が空の場合
         print("警告: ルールファイルが空か、読み込みに失敗しました。デフォルト制約のみ適用されます。")

    date_range = get_date_range(START_DATE, END_DATE)
    jp_holidays = get_holidays(START_DATE.year, END_DATE.year)
    employee_ids, emp_id_to_row_index = get_employee_indices(employees_df)

    # 2. (シミュレーション) AIによるルール整形＆パーサー実行
    print("Simulating AI rule shaping and parsing...")
    # TODO: 本来は natural_language_rules を AI API に渡して整形結果を得る
    # 今回はAIが出力するであろうJSONライクなPython辞書をシミュレート
    simulated_ai_output = {}
    # 例: EMP001 のルールを整形・構造化
    # (実際には、natural_language_rules[emp_id] をAIに渡してこの構造を得る)
    simulated_ai_output["EMP001"] = [
        {
            "confirmation_text": "EMP001さんは 2025-05-01 に「公休」固定となります。",
            "structured_data": {"rule_type": "ASSIGN", "employee": "EMP001", "date": "2025-05-01", "shift": "公", "is_hard": True}
        },
        {
            "confirmation_text": "EMP001さんの連続勤務は最大 4 日までです。",
            "structured_data": {"rule_type": "MAX_CONSECUTIVE_WORK", "employee": "EMP001", "max_days": 4}
        }
    ]
    simulated_ai_output["EMP002"] = [
        {
            "confirmation_text": "EMP002さんには「夜勤」は割り当てられません。",
            "structured_data": {"rule_type": "FORBID_SHIFT", "employee": "EMP002", "shift": "夜"}
        },
        {
            "confirmation_text": "EMP002さんは土日祝は勤務しません。",
            "structured_data": {"rule_type": "WEEKEND_HOLIDAY_OFF", "employee": "EMP002", "is_hard": True}
        }
    ]
    simulated_ai_output["EMP003"] = [
         {
            "confirmation_text": "EMP003さんとEMP004さんは同日に「夜勤」にはなりません。",
            "structured_data": {"rule_type": "FORBID_SIMULTANEOUS_SHIFT", "employee1": "EMP003", "employee2": "EMP004", "shift": "夜"}
        }
    ]
    simulated_ai_output["EMP004"] = []
    simulated_ai_output["EMP005"] = [
        {
            "confirmation_text": "EMP005さんの連続勤務は最大 3 日までです。",
            "structured_data": {"rule_type": "MAX_CONSECUTIVE_WORK", "employee": "EMP005", "max_days": 3}
        }
    ]
    simulated_ai_output["EMP006"] = [
        {
            "confirmation_text": "EMP006さんは 2025-05-05 に「早出」固定となります。",
            "structured_data": {"rule_type": "ASSIGN", "employee": "EMP006", "date": "2025-05-05", "shift": "早", "is_hard": True}
        }
    ]
    simulated_ai_output["EMP007"] = [
         {
            "confirmation_text": "EMP007さんは土日祝は勤務しません。",
            "structured_data": {"rule_type": "WEEKEND_HOLIDAY_OFF", "employee": "EMP007", "is_hard": True}
        }
    ]
    simulated_ai_output["EMP008"] = [
        {
            "confirmation_text": "EMP008さんには「日勤」「早出」のみ割り当て可能です。",
            "structured_data": {"rule_type": "ALLOW_ONLY_SHIFTS", "employee": "EMP008", "allowed_shifts": ["日", "早"]}
        }
    ]
    simulated_ai_output["EMP009"] = [
        {
            "confirmation_text": "EMP009さんは 2025-04-15 に「公休」固定となります。",
            "structured_data": {"rule_type": "ASSIGN", "employee": "EMP009", "date": "2025-04-15", "shift": "公", "is_hard": True}
        },
        {
            "confirmation_text": "EMP009さんは 2025-04-16 に「公休」固定となります。",
            "structured_data": {"rule_type": "ASSIGN", "employee": "EMP009", "date": "2025-04-16", "shift": "公", "is_hard": True}
        },
        {
            "confirmation_text": "EMP009さんは 2025-04-22 に「公休」固定となります。",
            "structured_data": {"rule_type": "ASSIGN", "employee": "EMP009", "date": "2025-04-22", "shift": "公", "is_hard": True}
        }
    ]
    # EMP010 は employees.csv に基づき追加 (合計公休数)
    simulated_ai_output["EMP010"] = [
        {
            "confirmation_text": "EMP010さんは期間中に最低 10 日の「公休」が必要です。",
            "structured_data": {"rule_type": "TOTAL_SHIFT_COUNT", "employee": "EMP010", "shifts": ["公"], "min": 10, "max": None}
        }
    ]

    # 新しいパーサーを実行
    structured_rules = parse_structured_rules_from_ai(simulated_ai_output)
    print(f"Parsed {len(structured_rules)} structured rules from AI output simulation.")
    # import pprint
    # pprint.pprint(structured_rules)

    # 3. OR-Toolsモデルの構築 (構造化ルールを使用)
    print("Building OR-Tools model with structured rules...")
    model, shifts_vars, employee_ids_from_model, date_range_from_model = build_shift_model(
        employees_df=employees_df,
        past_shifts_df=past_shifts_df,
        date_range=date_range,
        jp_holidays=jp_holidays,
        structured_rules=structured_rules
    )

    # 4. ソルバーの実行
    print("Solving the model...")
    status, solver = solve_shift_model(model)

    # 5. 結果の処理と出力
    print("Processing results...")
    # 5.1. 出力用DataFrameの初期化
    initial_shift_df = create_shift_dataframe(employees_df, date_range, jp_holidays)
    if initial_shift_df is None:
         print("エラー: 出力用DataFrameの初期化に失敗。")
         sys.exit(1)

    # 5.2. 過去シフトを出力DFに転記
    if past_shifts_df is not None:
        # 修正: past_shifts_df のカラム名を直接使う
        past_date_cols_input = past_shifts_df.columns[1:].tolist()
        past_date_cols_output = [(START_DATE - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(len(past_date_cols_input), 0, -1)] # 出力形式に合わせる
        past_shifts_lookup = past_shifts_df.set_index('職員ID')
        employee_data_start_row = 1
        for i, emp_id in enumerate(employee_ids):
            row_idx = employee_data_start_row + i
            if emp_id in past_shifts_lookup.index:
                 for input_col, output_col in zip(past_date_cols_input, past_date_cols_output):
                      initial_shift_df.loc[row_idx, output_col] = past_shifts_lookup.loc[emp_id, input_col]
            else:
                 for output_col in past_date_cols_output:
                      initial_shift_df.loc[row_idx, output_col] = ''

    # 5.3. ソルバー結果を処理してDataFrameに反映
    final_shift_df = process_solver_results(status, solver, shifts_vars, employee_ids, date_range, initial_shift_df, employees_df, jp_holidays)

    # 5.4. CSVに保存
    if final_shift_df is not None:
        save_shift_to_csv(final_shift_df, OUTPUT_DIR, START_DATE)
    else:
        print("エラー: シフト生成に失敗したため、CSVファイルは出力されませんでした。")

    print("--- Shift Generator Script End ---")

if __name__ == "__main__":
    main() 