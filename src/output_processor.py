# 結果処理・CSV出力
import pandas as pd
import os
from datetime import date, timedelta
from ortools.sat.python import cp_model
from collections import Counter

from src.constants import (
    SHIFT_MAP_SYM, SHIFT_MAP_INT,
    SUMMARY_COLS, DAY_SUMMARY_ROW_NAMES, START_DATE, END_DATE # create_shift_dataframe 用
)
from src.utils import get_employee_info

# create_shift_dataframe は output_processor に移動するのが適切か？
# もしくは utils か、独立したファイルか。
# ここでは output_processor に含めてみる

def create_shift_dataframe(employees_df, date_range, jp_holidays):
    """シフト表のDataFrameを初期化する (ヘッダー、曜日、職員名、集計行)"""
    if employees_df is None:
        print("エラー: create_shift_dataframe に従業員データがありません。")
        return None

    employee_ids_ordered = employees_df['職員ID'].tolist()
    num_employees = len(employee_ids_ordered)

    # 過去シフト表示はメインロジックで実施するため、ここでは生成期間のみ考慮
    # ただし、元の出力形式に合わせるなら過去日付列も作る
    past_date_cols_output = [(START_DATE - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(3, 0, -1)]
    target_date_cols = [d.strftime('%Y-%m-%d') for d in date_range]
    date_cols_output = past_date_cols_output + target_date_cols

    columns = ['職員名', '担当フロア'] + date_cols_output + SUMMARY_COLS
    num_rows = num_employees + 1 + len(DAY_SUMMARY_ROW_NAMES)
    df = pd.DataFrame('', index=range(num_rows), columns=columns)

    # 曜日行の設定 (index=0)
    df.iloc[0, 0] = ""
    df.iloc[0, 1] = ""
    for i, col_date_str in enumerate(date_cols_output):
        col_date = date.fromisoformat(col_date_str)
        weekday_jp = ["月", "火", "水", "木", "金", "土", "日"][col_date.weekday()]
        is_holiday = col_date in jp_holidays
        df.iloc[0, i + 2] = f"{weekday_jp}{'(祝)' if is_holiday else ''}"
    for i, col_name in enumerate(SUMMARY_COLS):
        df.iloc[0, i + 2 + len(date_cols_output)] = ""

    # 職員データ行の初期化 (index=1 から)
    employee_data_start_row = 1
    if '職員名' not in employees_df.columns:
         print("警告: 従業員情報に '職員名' カラムなし。'職員ID' を使用します。")
         df.iloc[employee_data_start_row : employee_data_start_row + num_employees, 0] = employees_df['職員ID'].values
    else:
         df.iloc[employee_data_start_row : employee_data_start_row + num_employees, 0] = employees_df['職員名'].values
    df.iloc[employee_data_start_row : employee_data_start_row + num_employees, 1] = employees_df['担当フロア'].fillna('').values
    # 過去シフトの転記はメインスクリプト側で行うか、ここで past_shifts_df を受け取るか

    # 集計行の初期化
    summary_row_start_index = employee_data_start_row + num_employees
    for i, name in enumerate(DAY_SUMMARY_ROW_NAMES):
        df.iloc[summary_row_start_index + i, 0] = name
        df.iloc[summary_row_start_index + i, 1] = ""

    print("シフト表の雛形 (DataFrame) を作成しました。")
    return df

def process_solver_results(status, solver, shifts_vars, employee_ids, date_range, initial_shift_df, employees_df, jp_holidays):
    """ソルバーの結果を処理し、シフト情報を埋めたDataFrameを返す"""
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print(f"Processing solution (Status: {solver.StatusName(status)}) ")
        filled_shift_df = initial_shift_df.copy()
        employee_data_start_row = 1
        target_date_cols = [d.strftime('%Y-%m-%d') for d in date_range]
        all_employees = range(len(employee_ids))
        all_days = range(len(date_range))

        emp_idx_to_id = {i: emp_id for i, emp_id in enumerate(employee_ids)}

        # DataFrameに結果を書き込む
        for e_idx in all_employees:
            row_index = employee_data_start_row + e_idx
            # emp_info = emp_id_to_info.get(emp_idx_to_id.get(e_idx)) # 応援表記で使わないなら不要
            # original_floor = emp_info['担当フロア'] if emp_info is not None else None

            for d_idx, date_col in enumerate(target_date_cols):
                target_date = date_range[d_idx]
                weekday = target_date.weekday()
                is_weekend_or_holiday = (weekday >= 5) or (target_date in jp_holidays)
                shift_int = solver.Value(shifts_vars[(e_idx, d_idx)])
                shift_sym = SHIFT_MAP_SYM.get(shift_int, '?')
                output_shift_sym = shift_sym # デフォルト

                # 応援表記の追加ロジックを削除 (is_helping_* を受け取らないため)
                # if shift_int in ... :
                #    ...

                filled_shift_df.loc[row_index, date_col] = output_shift_sym

        # --- 集計処理 ---
        print("Calculating summaries...")
        summary_cols_map = {
            '集計:公休': [SHIFT_MAP_INT['公']],
            #'集計:祝日': [], # 祝日勤務は別で考慮が必要
            '集計:日勤': [SHIFT_MAP_INT['日']],
            '集計:早出': [SHIFT_MAP_INT['早']],
            '集計:夜勤': [SHIFT_MAP_INT['夜']],
            '集計:明勤': [SHIFT_MAP_INT['明']]
        }
        # 職員別集計
        for e_idx in all_employees:
            row_index = employee_data_start_row + e_idx
            shift_counts = Counter(solver.Value(shifts_vars[(e_idx, d_idx)]) for d_idx in all_days)
            for col_name, symbols_int in summary_cols_map.items():
                count = sum(shift_counts[s_int] for s_int in symbols_int)
                filled_shift_df.loc[row_index, col_name] = count
            # TODO: 祝日勤務の集計

        # 日付別集計
        summary_row_start_index = employee_data_start_row + len(employee_ids)
        day_summary_map = {
             '日勤合計': [SHIFT_MAP_INT['日']], '早出合計': [SHIFT_MAP_INT['早']],
             '夜勤合計': [SHIFT_MAP_INT['夜']], '明勤合計': [SHIFT_MAP_INT['明']]
        }
        for i, (row_name, symbols_int) in enumerate(day_summary_map.items()):
             row_index = summary_row_start_index + i
             for d_idx, date_col in enumerate(target_date_cols):
                 count = sum(1 for e_idx in all_employees if solver.Value(shifts_vars[(e_idx, d_idx)]) in symbols_int)
                 filled_shift_df.loc[row_index, date_col] = count

        return filled_shift_df.fillna('')
    else:
        print("Solution not found.")
        return None

def save_shift_to_csv(shift_df, output_dir, start_date):
    """生成されたシフト表をCSVファイルに保存する (バージョン管理付き)"""
    os.makedirs(output_dir, exist_ok=True)
    base_filename = f"shift_{start_date.strftime('%Y%m%d')}"
    version = 1
    output_filename = f"{base_filename}.csv"
    output_path = os.path.join(output_dir, output_filename)
    while os.path.exists(output_path):
        output_filename = f"{base_filename}_v{version:02d}.csv"
        output_path = os.path.join(output_dir, output_filename)
        version += 1
    try:
        shift_df.to_csv(output_path, index=False, header=True, encoding='utf_8_sig')
        print(f"シフト表をCSVファイルに出力しました: {output_path}")
        return output_path # 保存したパスを返す
    except Exception as e:
        print(f"エラー: CSVファイルへの書き込み中にエラーが発生しました - {e}")
        return None 