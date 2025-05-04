# OR-Toolsモデル構築
from ortools.sat.python import cp_model
from datetime import timedelta, date

from src.constants import (
    SHIFT_MAP_INT, WORKING_SHIFTS_INT, OFF_SHIFT_INTS,
    REQUIRED_PERSONNEL, DEFAULT_MAX_CONSECUTIVE_WORK,
    MANAGER_MAX_CONSECUTIVE_WORK, MANAGER_ROLES,
    START_DATE,
    WORK_SYMBOLS # 応援変数定義で必要
)
from src.utils import get_employee_info # 役職や制約取得に使う

def build_shift_model(employees_df, past_shifts_df, date_range, jp_holidays, structured_rules):
    """OR-Tools CP-SATモデルを構築し、制約を追加する (構造化ルール入力版)"""
    model = cp_model.CpModel()
    print("Shift model building started...")

    # --- データ準備 ---
    employee_ids = employees_df['職員ID'].tolist()
    num_employees = len(employee_ids)
    num_days = len(date_range)
    all_employees = range(num_employees)
    all_days = range(num_days)

    emp_idx_to_id = {i: emp_id for i, emp_id in enumerate(employee_ids)}
    emp_id_to_idx = {emp_id: idx for idx, emp_id in emp_idx_to_id.items()}
    date_to_d_idx = {d: idx for idx, d in enumerate(date_range)}
    past_shifts_lookup = past_shifts_df.set_index('職員ID') if past_shifts_df is not None else None

    # --- 変数定義 ---
    shifts = {}
    max_shift_int_value = max(SHIFT_MAP_INT.values()) # SHIFT_MAP_INT の値の最大値 (5)
    for e in all_employees:
        for d in all_days:
            # 上限値を修正 (len(SHIFT_MAP_INT)-1 ではなく max_shift_int_value を使う)
            shifts[(e, d)] = model.NewIntVar(0, max_shift_int_value, f'shift_e{e}_d{d}')
    print("Variables defined.")

    # --- 応援変数定義 ---
    is_helping_1F_to_2F = {}
    is_helping_2F_to_1F = {}
    helpable_shifts_int = [SHIFT_MAP_INT[s] for s in ['日', '早']] # 応援可能なシフト(例: 日勤, 早出)

    for e_idx in all_employees:
        emp_info = get_employee_info(employees_df, emp_idx_to_id.get(e_idx))
        if emp_info is None: continue
        can_help = emp_info.get('can_help_other_floor', False)
        original_floor = emp_info.get('担当フロア')

        for d_idx in all_days:
            for s_int in helpable_shifts_int: # 日勤と早出のみ応援可能とする (仮)
                if original_floor == '1F' and can_help:
                     is_helping_1F_to_2F[(e_idx, d_idx, s_int)] = model.NewBoolVar(f'help_1_2_e{e_idx}_d{d_idx}_s{s_int}')
                if original_floor == '2F' and can_help:
                     is_helping_2F_to_1F[(e_idx, d_idx, s_int)] = model.NewBoolVar(f'help_2_1_e{e_idx}_d{d_idx}_s{s_int}')
    print("Help variables defined.")

    # --- 制約追加 ---
    print("Adding constraints from structured rules...")

    # ペナルティリストの初期化
    ab_schedule_penalties = []
    weekday_penalties = []
    night_preference_penalties = []
    ake_count_deviation_penalties = []
    total_off_day_deviation_penalties = []
    off_days_difference = None # 均等化用
    full_time_employee_indices = [] # 均等化用
    num_off_days_vars = {} # 均等化用

    # <<< 構造化ルールリストを処理して制約を追加 >>>
    processed_rule_types = set() # 複数回適用を防ぐため（連勤など）
    employee_specific_rules = {e_idx: [] for e_idx in all_employees} # 従業員ごとのルール
    for rule in structured_rules:
        employee_id = rule.get('employee')
        if employee_id not in emp_id_to_idx:
            print(f"警告: ルール内の従業員ID {employee_id} が見つかりません。ルールをスキップ: {rule}")
            continue
        e_idx = emp_id_to_idx[employee_id]
        employee_specific_rules[e_idx].append(rule)

    for e_idx in all_employees:
        emp_id = employee_ids[e_idx]
        emp_info = get_employee_info(employees_df, emp_id)
        if emp_info is None: continue

        # --- 従業員ごとのルールを適用 ---
        for rule in employee_specific_rules[e_idx]:
            rule_type = rule.get('rule_type')

            # 育休/病休 (基本情報から。ルールリストには含めない方が良いかも)
            current_status = emp_info.get('status')
            if current_status in ['育休', '病休']:
                 status_int = SHIFT_MAP_INT.get(current_status)
                 if status_int is not None:
                     for d_idx in all_days: model.Add(shifts[(e_idx, d_idx)] == status_int)
                 continue # 他のルールは適用しない
            # 育休/病休でないなら、それらのシフトを禁止
            if SHIFT_MAP_INT.get('育休') is not None:
                 for d_idx in all_days: model.Add(shifts[(e_idx, d_idx)] != SHIFT_MAP_INT['育休'])

            if rule_type == 'ASSIGN':
                target_date = rule.get('date')
                shift_sym = rule.get('shift')
                is_hard = rule.get('is_hard', True) # デフォルトはハード
                if target_date in date_to_d_idx and shift_sym in SHIFT_MAP_INT:
                    d_idx = date_to_d_idx[target_date]
                    shift_int = SHIFT_MAP_INT[shift_sym]
                    if is_hard:
                        model.Add(shifts[(e_idx, d_idx)] == shift_int)
                    else: # ソフト制約 (現在夜勤希望のみ該当想定)
                        penalty_var = model.NewBoolVar(f'pref_shift_penalty_e{e_idx}_d{d_idx}')
                        # リストを使い分ける？ -> night_preference_penalties で統一
                        if shift_int == SHIFT_MAP_INT.get('夜'):
                             night_preference_penalties.append(penalty_var)
                        else:
                             weekday_penalties.append(penalty_var) # 他の希望もweekdayに含める？要調整
                        model.Add(shifts[(e_idx, d_idx)] != shift_int).OnlyEnforceIf(penalty_var)
                        model.Add(shifts[(e_idx, d_idx)] == shift_int).OnlyEnforceIf(penalty_var.Not())
                # else: print(...) エラー処理

            elif rule_type == 'MAX_CONSECUTIVE_WORK':
                max_days = rule.get('max_days')
                if isinstance(max_days, int) and max_days >= 0 and f'max_work_{e_idx}' not in processed_rule_types:
                    # (連勤制約#6のロジック)
                    initial_consecutive_work = 0
                    if past_shifts_lookup is not None and emp_id in past_shifts_lookup.index:
                         for i in range(1, max_days + 2): # +2 for checking boundary
                              past_date_str = (START_DATE - timedelta(days=i)).strftime('%#m/%#d')
                              if past_date_str in past_shifts_lookup.columns:
                                  past_shift = past_shifts_lookup.loc[emp_id, past_date_str]
                                  if past_shift and past_shift not in ['公', '育休', '病休']:
                                      initial_consecutive_work += 1
                                  else: break
                              else: break
                    is_working = [model.NewBoolVar(f'is_work_r6_e{e_idx}_d{d_idx}') for d_idx in all_days]
                    allowed_tuples = [(s,) for s in WORKING_SHIFTS_INT]
                    for d_idx in all_days:
                         model.AddAllowedAssignments((shifts[(e_idx, d_idx)],), allowed_tuples).OnlyEnforceIf(is_working[d_idx])
                         model.AddForbiddenAssignments((shifts[(e_idx, d_idx)],), allowed_tuples).OnlyEnforceIf(is_working[d_idx].Not())
                    window_size = max_days + 1
                    for d_start in range(-initial_consecutive_work, num_days - max_days):
                         vars_in_window = []
                         for d_offset in range(window_size):
                              d_current = d_start + d_offset
                              if d_current < 0: continue
                              if d_current >= num_days: break
                              vars_in_window.append(is_working[d_current])
                         if d_start < 0:
                              effective_window_size = window_size + d_start
                              if effective_window_size > 0: model.Add(sum(vars_in_window) <= effective_window_size - 1)
                         elif vars_in_window: model.Add(sum(vars_in_window) <= max_days)
                    processed_rule_types.add(f'max_work_{e_idx}') # 処理済みマーク
                # else: print(...) エラー処理

            elif rule_type == 'FORBID_SHIFT':
                shift_sym = rule.get('shift')
                if shift_sym in SHIFT_MAP_INT:
                    shift_int = SHIFT_MAP_INT[shift_sym]
                    for d_idx in all_days:
                        model.Add(shifts[(e_idx, d_idx)] != shift_int)
                # else: print(...) エラー処理

            elif rule_type == 'WEEKEND_HOLIDAY_OFF':
                 if f'weekend_off_{e_idx}' not in processed_rule_types:
                    forbidden_shifts_int = WORKING_SHIFTS_INT
                    for d_idx in all_days:
                        target_date = date_range[d_idx]
                        weekday = target_date.weekday()
                        is_weekend_or_holiday = (weekday >= 5) or (target_date in jp_holidays)
                        if is_weekend_or_holiday:
                             for forbidden_int in forbidden_shifts_int:
                                  model.Add(shifts[(e_idx, d_idx)] != forbidden_int)
                    processed_rule_types.add(f'weekend_off_{e_idx}')
                 # is_hard は現在考慮不要

            elif rule_type == 'FORBID_SIMULTANEOUS_SHIFT':
                employee2_id = rule.get('employee2')
                shift_sym = rule.get('shift')
                rule_key = f"combo_{e_idx}_{employee2_id}_{shift_sym}"
                if employee2_id in emp_id_to_idx and shift_sym in SHIFT_MAP_INT and rule_key not in processed_rule_types:
                    e2_idx = emp_id_to_idx[employee2_id]
                    shift_int = SHIFT_MAP_INT[shift_sym]
                    for d_idx in all_days:
                        b1 = model.NewBoolVar(f'simul_e{e_idx}_d{d_idx}_s{shift_int}')
                        b2 = model.NewBoolVar(f'simul_e{e2_idx}_d{d_idx}_s{shift_int}')
                        model.Add(shifts[(e_idx, d_idx)] == shift_int).OnlyEnforceIf(b1)
                        model.Add(shifts[(e_idx, d_idx)] != shift_int).OnlyEnforceIf(b1.Not())
                        model.Add(shifts[(e2_idx, d_idx)] == shift_int).OnlyEnforceIf(b2)
                        model.Add(shifts[(e2_idx, d_idx)] != shift_int).OnlyEnforceIf(b2.Not())
                        model.AddBoolOr([b1.Not(), b2.Not()])
                    processed_rule_types.add(rule_key)
                    processed_rule_types.add(f"combo_{e2_idx}_{emp_id}_{shift_sym}") # 逆も登録
                # else: print(...) エラー処理

            elif rule_type == 'ALLOW_ONLY_SHIFTS':
                allowed_shifts_sym = rule.get('allowed_shifts')
                if isinstance(allowed_shifts_sym, list) and f'allow_{e_idx}' not in processed_rule_types:
                    allowed_ints = [SHIFT_MAP_INT[s] for s in allowed_shifts_sym if s in SHIFT_MAP_INT]
                    all_ints = list(SHIFT_MAP_INT.values())
                    forbidden_ints = [i for i in all_ints if i not in allowed_ints and i != SHIFT_MAP_INT['育休']]
                    if forbidden_ints:
                         for d_idx in all_days:
                              # 修正: AddForbiddenAssignments はリスト内のいずれかを禁止する
                              model.AddForbiddenAssignments((shifts[(e_idx, d_idx)],), [(f_int,) for f_int in forbidden_ints])
                    processed_rule_types.add(f'allow_{e_idx}')
                # else: print(...) エラー処理

            elif rule_type == 'TOTAL_SHIFT_COUNT':
                 target_shifts_sym = rule.get('shifts')
                 min_count = rule.get('min')
                 max_count = rule.get('max')
                 rule_key = f"total_{e_idx}_{'_'.join(target_shifts_sym)}_{min_count}_{max_count}"
                 if isinstance(target_shifts_sym, list) and rule_key not in processed_rule_types:
                      target_ints = [SHIFT_MAP_INT[s] for s in target_shifts_sym if s in SHIFT_MAP_INT]
                      if target_ints:
                           count_vars = []
                           allowed_tuples = [(t_int,) for t_int in target_ints]
                           for d_idx in all_days:
                                is_target = model.NewBoolVar(f'is_total_count_e{e_idx}_d{d_idx}_{rule_key[:10]}')
                                model.AddAllowedAssignments((shifts[(e_idx, d_idx)],), allowed_tuples).OnlyEnforceIf(is_target)
                                model.AddForbiddenAssignments((shifts[(e_idx, d_idx)],), allowed_tuples).OnlyEnforceIf(is_target.Not())
                                count_vars.append(is_target)
                           if min_count is not None: model.Add(sum(count_vars) >= min_count)
                           if max_count is not None: model.Add(sum(count_vars) <= max_count)
                           processed_rule_types.add(rule_key)
                      # else: print(...) エラー処理
                 # else: print(...) エラー処理

            # --- ソフト制約の処理 (structured_rules ベースに修正) ---
            elif rule_type == 'PREFER_WEEKDAY_SHIFT':
                 weekday = rule.get('weekday')
                 shift_sym = rule.get('shift')
                 if weekday is not None and shift_sym in SHIFT_MAP_INT:
                      shift_int = SHIFT_MAP_INT[shift_sym]
                      for d_idx in all_days:
                           if date_range[d_idx].weekday() == weekday:
                                penalty_var = model.NewBoolVar(f'weekday_penalty_e{e_idx}_d{d_idx}')
                                weekday_penalties.append(penalty_var)
                                model.Add(shifts[(e_idx, d_idx)] != shift_int).OnlyEnforceIf(penalty_var)
                                model.Add(shifts[(e_idx, d_idx)] == shift_int).OnlyEnforceIf(penalty_var.Not())
                 # else: print(...) エラー処理

            elif rule_type == 'TARGET_TOTAL_OFF_DAYS':
                 target_count = rule.get('target_count')
                 if isinstance(target_count, int) and target_count >= 0:
                      is_off_vars_total = []
                      off_day_int_total = SHIFT_MAP_INT['公']
                      for d_idx in all_days:
                           is_off_total = model.NewBoolVar(f'is_off_total_e{e_idx}_d{d_idx}')
                           model.Add(shifts[(e_idx, d_idx)] == off_day_int_total).OnlyEnforceIf(is_off_total)
                           model.Add(shifts[(e_idx, d_idx)] != off_day_int_total).OnlyEnforceIf(is_off_total.Not())
                           is_off_vars_total.append(is_off_total)
                      actual_off_count_expr = sum(is_off_vars_total)
                      max_possible_dev = num_days
                      deviation_var = model.NewIntVar(0, max_possible_dev, f'total_off_dev_e{e_idx}')
                      model.AddAbsEquality(deviation_var, actual_off_count_expr - target_count)
                      total_off_day_deviation_penalties.append(deviation_var)
                 # else: print(...) エラー処理

            # --- 以下、structured_rules から直接適用できない制約 (従業員情報や全体ループが必要) ---
            # elif rule_type == 'MAX_CONSECUTIVE_OFF': # 全体ルールへ移動
            # elif rule_type == 'PREFER_CALENDAR_SCHEDULE': # 全体ルールへ移動

            elif rule_type == 'UNKNOWN_FORMAT' or rule_type == 'PARSE_ERROR' or rule_type == 'UNPARSABLE':
                 print(f"情報(モデル): 処理できないルール: {rule}")
            # else: print(f"情報(モデル): 未対応のルールタイプ: {rule_type}")

    # <<< ここまで構造化ルールの処理 >>>

    # <<< 施設全体ルール & 従業員情報依存のルールの追加 >>>

    # 直前勤務 (#3) - (従業員ループが必要なのでここに残す)
    if past_shifts_lookup is not None:
        for e_idx in all_employees:
             emp_id = emp_idx_to_id.get(e_idx)
             emp_info = get_employee_info(employees_df, emp_id)
             if emp_info is not None and emp_info.get('status') not in ['育休', '病休'] and emp_id in past_shifts_lookup.index:
                 prev_date_str = (START_DATE - timedelta(days=1)).strftime('%#m/%#d')
                 prev_2_date_str = (START_DATE - timedelta(days=2)).strftime('%#m/%#d')
                 prev_shift = past_shifts_lookup.loc[emp_id, prev_date_str] if prev_date_str in past_shifts_lookup.columns else None
                 prev_2_shift = past_shifts_lookup.loc[emp_id, prev_2_date_str] if prev_2_date_str in past_shifts_lookup.columns else None
                 if prev_shift == '夜': model.Add(shifts[(e_idx, 0)] == SHIFT_MAP_INT['明'])
                 elif prev_shift == '明': model.Add(shifts[(e_idx, 0)] == SHIFT_MAP_INT['公'])
                 elif prev_2_shift == '夜' and prev_shift == '明': model.Add(shifts[(e_idx, 0)] == SHIFT_MAP_INT['公'])

    # 人員配置基準 (#4) - 応援なし版に簡略化 (実験スコープ)
    # ... (元のコードを維持 - 修正: 実験スコープに合わせて total_required_personnel を計算)
    personnel_key_map = {"日勤": "日", "早出": "早", "夜勤": "夜"}
    total_required_personnel = {}
    for shift_sym in [personnel_key_map[k] for k in personnel_key_map]:
        shift_int = SHIFT_MAP_INT.get(shift_sym)
        if shift_int is not None:
             verbose_key = next((vk for vk, vs in personnel_key_map.items() if vs == shift_sym), None)
             if verbose_key and '1F' in REQUIRED_PERSONNEL: # 実験用に1Fのみ参照
                  total_needed = REQUIRED_PERSONNEL['1F'].get(verbose_key, 0)
                  if total_needed > 0:
                       total_required_personnel[shift_int] = total_needed
    # 制約追加
    for d_idx in all_days:
        for shift_int, required_count in total_required_personnel.items():
            # 修正: ブール変数を使う方法に戻す
            personnel_bool_vars = []
            for e_idx in all_employees:
                emp_info = get_employee_info(employees_df, employee_ids[e_idx])
                if emp_info is not None:
                    status = emp_info.get('status', '')
                    if status in ['育休', '病休']: continue
                is_assigned_total = model.NewBoolVar(f'is_total_assigned_e{e_idx}_d{d_idx}_s{shift_int}')
                model.Add(shifts[(e_idx, d_idx)] == shift_int).OnlyEnforceIf(is_assigned_total)
                model.Add(shifts[(e_idx, d_idx)] != shift_int).OnlyEnforceIf(is_assigned_total.Not())
                personnel_bool_vars.append(is_assigned_total)
            model.Add(sum(personnel_bool_vars) == required_count)

    # 夜勤ローテ (#5) - 全員に適用
    for e_idx in all_employees:
        emp_info = get_employee_info(employees_df, emp_idx_to_id.get(e_idx))
        if emp_info is not None and emp_info.get('status') in ['育休', '病休']: continue
        for d_idx in range(num_days - 1):
            b_night = model.NewBoolVar(f'b_n_e{e_idx}d{d_idx}')
            model.Add(shifts[(e_idx, d_idx)] == SHIFT_MAP_INT['夜']).OnlyEnforceIf(b_night)
            model.Add(shifts[(e_idx, d_idx)] != SHIFT_MAP_INT['夜']).OnlyEnforceIf(b_night.Not())
            model.Add(shifts[(e_idx, d_idx + 1)] == SHIFT_MAP_INT['明']).OnlyEnforceIf(b_night)
            b_ake = model.NewBoolVar(f'b_a_e{e_idx}d{d_idx}')
            model.Add(shifts[(e_idx, d_idx)] == SHIFT_MAP_INT['明']).OnlyEnforceIf(b_ake)
            model.Add(shifts[(e_idx, d_idx)] != SHIFT_MAP_INT['明']).OnlyEnforceIf(b_ake.Not())
            model.Add(shifts[(e_idx, d_idx + 1)] == SHIFT_MAP_INT['公']).OnlyEnforceIf(b_ake)

    # 副主任勤務 (#14) - 役職情報が必要なのでここに残す
    vice_manager_indices = [e_idx for e_idx in all_employees if (emp_info := get_employee_info(employees_df, emp_idx_to_id.get(e_idx))) is not None and emp_info.get('役職') == '副主任' and emp_info.get('status') not in ['育休', '病休']]
    if vice_manager_indices:
        for d_idx in all_days:
            target_date = date_range[d_idx]
            weekday = target_date.weekday()
            is_weekend_or_holiday = (weekday >= 5) or (target_date in jp_holidays)
            if is_weekend_or_holiday:
                is_off_vm_vars = []
                off_shift_ints_vm = OFF_SHIFT_INTS
                allowed_off_tuples = [(s,) for s in off_shift_ints_vm]
                for vm_idx in vice_manager_indices:
                    is_off = model.NewBoolVar(f'is_off_vm_e{vm_idx}_d{d_idx}')
                    model.AddAllowedAssignments((shifts[(vm_idx, d_idx)],), allowed_off_tuples).OnlyEnforceIf(is_off)
                    model.AddForbiddenAssignments((shifts[(vm_idx, d_idx)],), allowed_off_tuples).OnlyEnforceIf(is_off.Not())
                    is_off_vm_vars.append(is_off)
                model.Add(sum(is_off_vm_vars) <= len(vice_manager_indices) - 1)

    # <<< ソフト制約のペナルティ計算 >>>
    # (曜日希望、カレンダー勤務、明け人数、特定パート休日数目標はここで計算)
    # ... (それぞれのソフト制約に対応するペナルティリストへの追加ロジックを実装) ...
    # 例: カレンダー勤務 (A/B)
    calendar_employees = [emp_id_to_idx.get('A'), emp_id_to_idx.get('B')] # インデックスに変換
    calendar_employees = [e for e in calendar_employees if e is not None]
    default_work_shift = SHIFT_MAP_INT['日']
    weekend_off_shift = SHIFT_MAP_INT['公']
    for e_idx in calendar_employees:
         emp_info = get_employee_info(employees_df, emp_idx_to_id.get(e_idx))
         if emp_info is None or emp_info.get('status') in ['育休', '病休']: continue
         # requested_holidays = emp_info.get('parsed_holidays', []) # parsed_holidays はもう無い
         # -> 代わりにハード制約でASSIGNされているかチェック？ or 単純に全日見る？ -> 全日見る
         for d_idx in all_days:
              target_date = date_range[d_idx]
              weekday = target_date.weekday()
              penalty_var = model.NewBoolVar(f'ab_penalty_e{e_idx}_d{d_idx}')
              ab_schedule_penalties.append(penalty_var)
              if weekday >= 5:
                   model.Add(shifts[(e_idx, d_idx)] != weekend_off_shift).OnlyEnforceIf(penalty_var)
                   model.Add(shifts[(e_idx, d_idx)] == weekend_off_shift).OnlyEnforceIf(penalty_var.Not())
              else:
                   model.Add(shifts[(e_idx, d_idx)] != default_work_shift).OnlyEnforceIf(penalty_var)
                   model.Add(shifts[(e_idx, d_idx)] == default_work_shift).OnlyEnforceIf(penalty_var.Not())

    # ソフト制約 3: 明け人数≒前日夜勤人数 (ペナルティ変数リストに追加)
    night_shift_int = SHIFT_MAP_INT['夜']
    ake_shift_int = SHIFT_MAP_INT['明']
    for d_idx in all_days:
        # 修正: ブール変数 is_ake のリストを作成
        ake_today_bool_vars = []
        for e_idx in all_employees:
            is_ake = model.NewBoolVar(f'is_ake_total_e{e_idx}_d{d_idx}')
            model.Add(shifts[(e_idx, d_idx)] == ake_shift_int).OnlyEnforceIf(is_ake)
            model.Add(shifts[(e_idx, d_idx)] != ake_shift_int).OnlyEnforceIf(is_ake.Not())
            ake_today_bool_vars.append(is_ake)
        ake_today_sum = sum(ake_today_bool_vars) # PythonのsumでOK

        # 修正: 前日の夜勤合計もブール変数で
        night_yesterday_sum_expr = None
        if d_idx > 0:
             night_yesterday_bool_vars = []
             for e_idx in all_employees:
                  is_night_yd = model.NewBoolVar(f'is_night_yd_e{e_idx}_d{d_idx-1}')
                  model.Add(shifts[(e_idx, d_idx - 1)] == night_shift_int).OnlyEnforceIf(is_night_yd)
                  model.Add(shifts[(e_idx, d_idx - 1)] != night_shift_int).OnlyEnforceIf(is_night_yd.Not())
                  night_yesterday_bool_vars.append(is_night_yd)
             night_yesterday_sum_expr = sum(night_yesterday_bool_vars) # PythonのsumでOK
        else:
             count_night_last_day = 0
             if past_shifts_lookup is not None:
                  prev_date_str = (START_DATE - timedelta(days=1)).strftime('%#m/%#d')
                  if prev_date_str in past_shifts_lookup.columns:
                       count_night_last_day = sum(1 for emp_id in past_shifts_lookup.index if past_shifts_lookup.loc[emp_id, prev_date_str] == '夜')
             night_yesterday_sum_expr = count_night_last_day

        # 差の絶対値をペナルティとする
        max_possible_deviation = num_employees
        deviation_var = model.NewIntVar(0, max_possible_deviation, f'ake_dev_d{d_idx}')
        model.AddAbsEquality(deviation_var, ake_today_sum - night_yesterday_sum_expr)
        ake_count_deviation_penalties.append(deviation_var)

    # ソフト制約 4: 特定パート合計公休日数目標 (ペナルティ変数リストに追加)
    specific_total_offs = {'Q': 14, 'AM': 15, 'AN': 14, 'AO': 13, 'AL': 11}
    off_day_int_total = SHIFT_MAP_INT['公']
    for emp_id, target_off_count in specific_total_offs.items():
         if emp_id in emp_id_to_idx:
              e_idx = emp_id_to_idx[emp_id]
              emp_info = get_employee_info(employees_df, emp_id)
              if emp_info is not None:
                  status = emp_info.get('status', '')
                  if status in ['育休', '病休']: continue
              actual_off_count_expr = cp_model.LinearExpr.Sum([shifts[(e_idx, d_idx)] == off_day_int_total for d_idx in all_days])
              max_possible_dev = num_days
              deviation_var = model.NewIntVar(0, max_possible_dev, f'total_off_dev_e{e_idx}')
              model.AddAbsEquality(deviation_var, actual_off_count_expr - target_off_count)
              total_off_day_deviation_penalties.append(deviation_var)

    # ソフト制約 5: 公休均等化 (一時的にコメントアウト開始)
    # full_time_employee_indices = []
    # for e_idx in all_employees:
    #     emp_info = get_employee_info(employees_df, emp_idx_to_id.get(e_idx))
    #     if emp_info is not None: # None チェック
    #         status = emp_info.get('status', '')
    #         job_type = emp_info.get('常勤/パート', '')
    #         if status not in ['育休', '病休'] and 'パート' not in job_type:
    #             full_time_employee_indices.append(e_idx)
    # off_days_difference = None # 初期化
    # if len(full_time_employee_indices) > 1:
    #     num_off_days_vars = {}
    #     off_day_int_eq = SHIFT_MAP_INT['公']
    #     for e_idx in full_time_employee_indices:
    #          off_count_expr = cp_model.LinearExpr.Sum([shifts[(e_idx, d_idx)] == off_day_int_eq for d_idx in all_days])
    #          num_off_days_vars[e_idx] = off_count_expr # 式を直接格納
    #     min_off_days = model.NewIntVar(0, num_days, 'min_off_days')
    #     max_off_days = model.NewIntVar(0, num_days, 'max_off_days')
    #     model.AddMinEquality(min_off_days, list(num_off_days_vars.values()))
    #     model.AddMaxEquality(max_off_days, list(num_off_days_vars.values()))
    #     off_days_difference = model.NewIntVar(0, num_days, 'off_days_diff')
    #     model.Add(off_days_difference == max_off_days - min_off_days)
    # ソフト制約 5: 公休均等化 (一時的にコメントアウト終了)

    # ソフト制約 6: 特定日付の夜勤希望 (Constraint #7の一部で night_preference_penalties に追加済み)
    # (night_preference_penalties は Constraint #7 (ASSIGN) の処理ループで作成済み)

    # --- 目的関数 --- (公休均等化ペナルティを除外)
    objective_terms = []
    ab_penalty_weight = 0.2
    weekday_penalty_weight = 1
    night_pref_penalty_weight = 1
    help_penalty_weight = 1
    ake_deviation_penalty_weight = 1
    total_off_day_penalty_weight = 1
    # off_balance_penalty_weight = 1 # コメントアウトしたので不要

    if ab_schedule_penalties: objective_terms.append(ab_penalty_weight * cp_model.LinearExpr.Sum(ab_schedule_penalties))
    if weekday_penalties: objective_terms.append(weekday_penalty_weight * cp_model.LinearExpr.Sum(weekday_penalties))
    if night_preference_penalties: objective_terms.append(night_pref_penalty_weight * cp_model.LinearExpr.Sum(night_preference_penalties))
    # if all_help_vars: objective_terms.append(help_penalty_weight * cp_model.LinearExpr.Sum(all_help_vars)) # 応援スコープ外
    if ake_count_deviation_penalties: objective_terms.append(ake_deviation_penalty_weight * cp_model.LinearExpr.Sum(ake_count_deviation_penalties))
    if total_off_day_deviation_penalties: objective_terms.append(total_off_day_penalty_weight * cp_model.LinearExpr.Sum(total_off_day_deviation_penalties))
    # if off_days_difference is not None: # 公休均等化はコメントアウト中
    #     objective_terms.append(off_balance_penalty_weight * off_days_difference)

    if objective_terms:
        model.Minimize(cp_model.LinearExpr.Sum(objective_terms))
        print("Objective function set: Minimize Weighted Penalties (Off Balance Excluded).")
    else:
        print("No objective function set.")

    print("Constraints added.")
    return model, shifts, employee_ids, date_range 