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
from src.data_loader import load_employee_data, load_past_shifts
from src.utils import get_date_range, get_holidays, get_employee_indices
from src.shift_model import build_shift_model
from src.solver import solve_shift_model
from src.output_processor import create_shift_dataframe, process_solver_results, save_shift_to_csv

def main():
    """メイン処理"""
    print("--- Shift Generator Script Start ---")

    # 1. データの読み込みと準備
    print("Loading data...")
    employees_df = load_employee_data(EMPLOYEE_INFO_FILE)
    past_shifts_df = load_past_shifts(PAST_SHIFT_FILE, START_DATE)

    if employees_df is None:
        print("エラー: 従業員情報の読み込みに失敗しました。処理を中断します。")
        sys.exit(1)
    # past_shifts_df はオプション扱いでも良いかもしれない
    # if past_shifts_df is None:
    #     print("警告: 直前勤務実績の読み込みに失敗しました。一部制約が適用されない可能性があります。")

    date_range = get_date_range(START_DATE, END_DATE)
    jp_holidays = get_holidays(START_DATE.year, END_DATE.year)
    employee_ids, emp_id_to_row_index = get_employee_indices(employees_df)

    # 2. OR-Toolsモデルの構築
    print("Building OR-Tools model...")
    model, shifts_vars, employee_ids_from_model, date_range_from_model = build_shift_model(employees_df, past_shifts_df, date_range, jp_holidays)

    # 3. ソルバーの実行
    print("Solving the model...")
    status, solver = solve_shift_model(model)

    # 4. 結果の処理と出力
    print("Processing results...")
    # 4.1. 出力用DataFrameの初期化
    initial_shift_df = create_shift_dataframe(employees_df, date_range, jp_holidays)
    if initial_shift_df is None:
         print("エラー: 出力用DataFrameの初期化に失敗。")
         sys.exit(1)

    # 4.2. 過去シフトを出力DFに転記 (オプションだが、元の出力形式に合わせる)
    if past_shifts_df is not None:
        past_date_cols_input = [(START_DATE - timedelta(days=i)).strftime('%#m/%#d') for i in range(3, 0, -1)]
        past_date_cols_output = [(START_DATE - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(3, 0, -1)]
        past_shifts_lookup = past_shifts_df.set_index('職員ID')
        employee_data_start_row = 1
        for i, emp_id in enumerate(employee_ids):
            row_idx = employee_data_start_row + i
            if emp_id in past_shifts_lookup.index:
                 for input_col, output_col in zip(past_date_cols_input, past_date_cols_output):
                      if input_col in past_shifts_lookup.columns:
                           initial_shift_df.loc[row_idx, output_col] = past_shifts_lookup.loc[emp_id, input_col]
                      else:
                           initial_shift_df.loc[row_idx, output_col] = '' # データなし
            else:
                 for output_col in past_date_cols_output:
                      initial_shift_df.loc[row_idx, output_col] = '' # データなし

    # 4.3. ソルバー結果を処理してDataFrameに反映
    final_shift_df = process_solver_results(status, solver, shifts_vars, employee_ids, date_range, initial_shift_df, employees_df, jp_holidays)

    # 4.4. CSVに保存
    if final_shift_df is not None:
        save_shift_to_csv(final_shift_df, OUTPUT_DIR, START_DATE)
    else:
        print("エラー: シフト生成に失敗したため、CSVファイルは出力されませんでした。")

    print("--- Shift Generator Script End ---")

if __name__ == "__main__":
    main() 