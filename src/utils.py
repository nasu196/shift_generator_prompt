# ユーティリティ関数
from datetime import date, timedelta
import holidays

def get_date_range(start_date, end_date):
    """指定された期間の日付リストを生成する"""
    return [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]

def get_holidays(start_year, end_year):
    """指定された年の日本の祝日を取得する"""
    jp_holidays = holidays.JP(years=start_year) # holidays v0.44 では years を使う
    if start_year != end_year:
        # 複数年にまたがる場合、それぞれの年の祝日を追加
        for year in range(start_year + 1, end_year + 1):
             jp_holidays.update(holidays.JP(years=year))
    return jp_holidays

def get_employee_indices(employees_df):
    """職員IDリストと、IDからDataFrameの行インデックス(シフト表上の)を引くための辞書を作成"""
    employee_ids = employees_df['職員ID'].tolist()
    emp_id_to_row_index = {emp_id: i + 1 for i, emp_id in enumerate(employee_ids)} # シフト表の職員行は1行目から
    return employee_ids, emp_id_to_row_index

def get_employee_info(employees_df, emp_id):
    """職員IDに対応する従業員情報を取得 (Seriesで返す)"""
    # 効率化のため、あらかじめ employees_df を ID でインデックス化しておく方が良い
    emp_data = employees_df[employees_df['職員ID'] == emp_id]
    if not emp_data.empty:
        return emp_data.iloc[0]
    return None 