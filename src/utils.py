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
    print(f"DEBUG (get_employee_info): ENTERED. Received emp_id='{emp_id}' (type: {type(emp_id)})")
    # --- DEBUG START: get_employee_info ---
    # print(f"DEBUG (get_employee_info): Called with emp_id='{emp_id}' (type: {type(emp_id)})") #重複なのでコメントアウト
    if employees_df is None or employees_df.empty:
        print("DEBUG (get_employee_info): employees_df is None or empty!")
        return None
    if '職員ID' not in employees_df.columns:
        print("DEBUG (get_employee_info): '職員ID' column not in employees_df!")
        return None
    print(f"DEBUG (get_employee_info): employees_df['職員ID'] dtype: {employees_df['職員ID'].dtype}")
    # 最初の数件の職員IDとその型を表示（比較のため）
    if not employees_df.empty:
        print(f"DEBUG (get_employee_info): Sample 職員ID from df (first 3): {employees_df['職員ID'].head(3).tolist()}")
        print(f"DEBUG (get_employee_info): Sample 職員ID types from df (first 3): {[type(x) for x in employees_df['職員ID'].head(3)]}")
    # --- DEBUG END ---

    # 効率化のため、あらかじめ employees_df を ID でインデックス化しておく方が良い
    emp_data = employees_df[employees_df['職員ID'] == emp_id]
    if not emp_data.empty:
        # print(f"DEBUG (get_employee_info): Found data for {emp_id}") # 必要ならコメント解除
        return emp_data.iloc[0]
    else:
        # print(f"DEBUG (get_employee_info): No data found for {emp_id}") # 必要ならコメント解除
        return None 

def get_employees_by_group(employees_df, group_name, emp_id_to_idx_arg):
    """指定されたグループ名に属する従業員のインデックスリストを返す"""
    print(f"DEBUG (get_employees_by_group): Requesting group: '{group_name}'")
    target_indices = []

    # --- 受け取った emp_id_to_idx_arg の型と内容を徹底的に確認 ---
    print(f"  DEBUG (get_employees_by_group): Received emp_id_to_idx_arg. Type: {type(emp_id_to_idx_arg)}, Size: {len(emp_id_to_idx_arg) if hasattr(emp_id_to_idx_arg, '__len__') else 'N/A'}")
    if isinstance(emp_id_to_idx_arg, dict) and emp_id_to_idx_arg:
        first_key = next(iter(emp_id_to_idx_arg))
        print(f"  DEBUG (get_employees_by_group): First key in emp_id_to_idx_arg: '{first_key}' (type: {type(first_key)})")
        print(f"  DEBUG (get_employees_by_group): First value in emp_id_to_idx_arg: '{emp_id_to_idx_arg[first_key]}' (type: {type(emp_id_to_idx_arg[first_key])})")
    elif not emp_id_to_idx_arg:
        print("  DEBUG (get_employees_by_group): emp_id_to_idx_arg is empty or None!")
        return []
    else:
        print("  DEBUG (get_employees_by_group): emp_id_to_idx_arg is NOT a dictionary!")
        return [] # 辞書でなければ処理できない

    print(f"  DEBUG: Starting loop through {len(emp_id_to_idx_arg)} employee mappings...")
    for eid_key, idx_val in emp_id_to_idx_arg.items(): # ループ変数を明確化 (キーがeid, 値がidxのはず)
        print(f"    DEBUG (Loop Start): Key from items(): '{eid_key}' (type: {type(eid_key)}), Value: {idx_val} (type: {type(idx_val)})")
        
        if not isinstance(eid_key, str):
            print(f"    ERROR (get_employees_by_group): Key '{eid_key}' is NOT a string! Skipping this entry.")
            continue

        current_eid_to_pass = eid_key # キーが文字列であることを確認済み
        
        # print(f"    >>> CRITICAL DEBUG (get_employees_by_group): About to call get_employee_info with current_eid_to_pass='{current_eid_to_pass}' (type: {type(current_eid_to_pass)}) for group '{group_name}'") # 必須ログではないので一旦コメントアウト
        emp_info = get_employee_info(employees_df, current_eid_to_pass) 
        
        if emp_info is None: 
            # print(f"      -> Skipping eid_key='{eid_key}' because get_employee_info returned None.") # 必要ならコメント解除
            continue
        
        status_val = emp_info.get('status', '[KEY_NOT_FOUND]')
        job_type_val = emp_info.get('常勤/パート', '[KEY_NOT_FOUND]')
        # role_val = emp_info.get('役職', '[KEY_NOT_FOUND]') # role_valの参照先がおかしいため修正
        role_val = emp_info.get('役職') if emp_info is not None else '[KEY_NOT_FOUND]' 

        # print(f"      -> Retrieved: status='{status_val}', job_type='{job_type_val}', role='{role_val}'")

        if pd.notna(status_val) and status_val in ['育休', '病休']:
            # print(f"      -> Skipping eid_key={eid_key} due to status: {status_val}")
            continue

        belongs = False
        if group_name == "ALL":
            belongs = True
        elif group_name == "常勤":
            if job_type_val == '常勤':
                belongs = True
        elif group_name == "パート":
            # job_type_raw が未定義だったので job_type_val を使うように修正
            if job_type_val != '[KEY_NOT_FOUND]' and job_type_val is not None:
                 job_type = str(job_type_val).strip().strip('"')
                 if 'パート' in job_type:
                     belongs = True
        else: # 役職名
            # role が未定義だったので role_val を使うように修正
            if role_val != '[KEY_NOT_FOUND]' and isinstance(role_val, str) and role_val == group_name:
                belongs = True
        
        if belongs:
            target_indices.append(idx_val) 

    print(f"DEBUG (get_employees_by_group): Found {len(target_indices)} indices for group '{group_name}': {target_indices}")

    # グループが見つからなかった場合の警告
    if not target_indices:
         if group_name not in ["ALL", "常勤", "パート"]:
              print(f"警告: 従業員情報にグループ/役職名 '{group_name}' が見つからないか、対象者がいません。")
         elif group_name in ["常勤", "パート"]:
              print(f"警告: グループ '{group_name}' に属する有効な従業員が見つかりません。")

    return target_indices 