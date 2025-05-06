# ユーティリティ関数
from datetime import date, timedelta
import holidays
from src.constants import MANAGER_ROLES # 役職名を使う場合
import pandas as pd

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

def get_employees_by_group(employees_df, group_name, emp_id_to_idx):
    """指定されたグループ名に属する従業員のインデックスリストを返す"""
    print(f"DEBUG (get_employees_by_group): Requesting group: '{group_name}'")
    target_indices = []
    # --- emp_id_to_idx の内容確認 ---
    print(f"  DEBUG: emp_id_to_idx type: {type(emp_id_to_idx)}, size: {len(emp_id_to_idx)}")
    if not emp_id_to_idx:
        print("DEBUG (get_employees_by_group): emp_id_to_idx is empty!")
        return []

    print(f"  DEBUG: Starting loop through {len(emp_id_to_idx)} employee indices...")
    for idx, eid in emp_id_to_idx.items():
        # --- ループ内部の詳細デバッグ --- 
        print(f"    DEBUG (Loop Start): Checking eid={eid}, idx={idx}") 
        emp_info = get_employee_info(employees_df, eid)
        if emp_info is None: 
            print(f"      -> Skipping eid={eid} because emp_info is None.")
            continue
        
        # .get()で取得した値を確認
        status_val = emp_info.get('status', '[KEY_NOT_FOUND]')
        job_type_val = emp_info.get('常勤/パート', '[KEY_NOT_FOUND]')
        role_val = emp_info.get('役職', '[KEY_NOT_FOUND]')
        print(f"      -> Retrieved: status='{status_val}', job_type='{job_type_val}', role='{role_val}'")

        # status が NaN でないか、かつ育休/病休でないかチェック
        if pd.notna(status_val) and status_val in ['育休', '病休']:
            print(f"      -> Skipping eid={eid} due to status: {status_val}")
            continue

        belongs = False
        if group_name == "ALL":
            print(f"      -> Checking for ALL group... MATCH!")
            belongs = True
        elif group_name == "常勤":
            print(f"      -> Checking for 常勤 group...")
            if job_type_val != '[KEY_NOT_FOUND]' and job_type_val is not None:
                job_type = str(job_type_val).strip().strip('"')
                print(f"        -> Comparing '{job_type}' == '常勤'")
                if job_type == '常勤':
                    print(f"          -> Match found for 常勤!")
                    belongs = True
                else:
                    print(f"          -> No match for 常勤.")
            else:
                print(f"      -> job_type_raw is None.")
        elif group_name == "パート":
             print(f"    -> Checking for パート group...")
             if job_type_raw is not None:
                 job_type = str(job_type_raw).strip().strip('"')
                 print(f"      -> job_type after cleaning: '{job_type}'")
                 if 'パート' in job_type:
                     print(f"        -> Match found for パート!")
                     belongs = True
                 else:
                    print(f"        -> No match for パート.")
             else:
                 print(f"      -> job_type_raw is None.")
        else:
            # 役職名でフィルタリング
            print(f"    -> Checking for role group: '{group_name}'...")
            if isinstance(role, str) and role == group_name:
                print(f"        -> Match found for role!")
                belongs = True
            else:
                 print(f"        -> No match for role (role is '{role}').")
        
        if belongs:
            print(f"    => Appending index {idx} for group '{group_name}'.")
            target_indices.append(idx)
        else:
            print(f"    => NOT Appending index {idx} for group '{group_name}'.") # 追加されなかった場合も表示

    print(f"DEBUG (get_employees_by_group): Found {len(target_indices)} indices for group '{group_name}': {target_indices}")

    # グループが見つからなかった場合の警告
    if not target_indices:
         if group_name not in ["ALL", "常勤", "パート"]:
              print(f"警告: 従業員情報にグループ/役職名 '{group_name}' が見つからないか、対象者がいません。")
         elif group_name in ["常勤", "パート"]:
              print(f"警告: グループ '{group_name}' に属する有効な従業員が見つかりません。")

    return target_indices 