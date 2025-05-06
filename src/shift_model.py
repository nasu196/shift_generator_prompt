# OR-Toolsモデル構築
from ortools.sat.python import cp_model
from datetime import timedelta, date

from src.constants import (
    SHIFT_MAP_INT, WORKING_SHIFTS_INT, OFF_SHIFT_INTS,
    DEFAULT_MAX_CONSECUTIVE_WORK,
    MANAGER_MAX_CONSECUTIVE_WORK, MANAGER_ROLES,
    START_DATE,
    WORK_SYMBOLS # 応援変数定義で必要
)
from src.utils import get_employee_info, get_employees_by_group # 役職や制約取得に使う

def build_shift_model(employees_df, past_shifts_df, date_range, jp_holidays, personal_rules, facility_rules):
    """OR-Tools CP-SATモデルを構築し、制約を追加する (個人ルール+施設ルール入力版)"""
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
    print("Adding constraints...")

    # ペナルティリストの初期化
    ab_schedule_penalties = []
    weekday_penalties = []
    night_preference_penalties = []
    ake_count_deviation_penalties = []
    max_consecutive_work_penalties = []
    max_consecutive_off_penalties = []
    total_shift_count_penalties = []
    balance_off_days_penalties = []
    total_staffing_penalties = [] # 人員配置不足ペナルティ
    over_staffing_penalties = []  # 超過ペナルティ用 (新規追加)
    min_role_penalties = [] # 役割最低出勤不足ペナルティ
    forbid_sequence_penalties = [] # 新しいペナルティリスト
    enforce_sequence_penalties = [] # 新しいペナルティリスト
    balance_specific_shift_penalties = [] # 新しいペナルティリスト
    facility_min_total_shift_penalties = [] # 新しいペナルティリスト (ソフト制約用)
    facility_max_consecutive_work_penalties = [] # 新しいペナルティリスト (ソフト制約用)
    off_days_difference = None # 均等化用
    full_time_employee_indices = [] # 均等化用
    num_off_days_vars = {} # 均等化用

    # <<< 個人ルールの処理 >>>
    print("Processing personal rules...")
    processed_rule_types = set()
    employee_specific_rules = {e_idx: [] for e_idx in all_employees}
    for rule in personal_rules:
        employee_id = rule.get('employee')
        employee1_id = rule.get('employee1')
        primary_e_idx = emp_id_to_idx.get(employee_id)
        employee1_idx = emp_id_to_idx.get(employee1_id)
        assign_to_idx = None
        if primary_e_idx is not None: assign_to_idx = primary_e_idx
        elif employee1_idx is not None: assign_to_idx = employee1_idx
        if assign_to_idx is not None:
             employee_specific_rules[assign_to_idx].append(rule)
        else:
            invalid_id_info = f"employee='{employee_id}' or employee1='{employee1_id}'"
            print(f"警告(個人): ルール内の従業員ID ({invalid_id_info}) が見つからないか、ルールを関連付けられません。ルールをスキップ: {rule}")
            continue

    for e_idx in all_employees:
        emp_id = employee_ids[e_idx]
        emp_info = get_employee_info(employees_df, emp_id)
        if emp_info is None:
            print(f"警告(個人モデル): 従業員情報が見つかりません: {emp_id}")
            continue

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

            # 'ASSIGN' から 'SPECIFY_DATE_SHIFT' に変更
            if rule_type == 'SPECIFY_DATE_SHIFT':
                target_date = rule.get('date')
                shift_sym = rule.get('shift')
                is_hard = rule.get('is_hard', True) # is_hard を取得 (デフォルトTrueはやめる)

                if target_date in date_to_d_idx and shift_sym in SHIFT_MAP_INT and isinstance(is_hard, bool):
                    d_idx = date_to_d_idx[target_date]
                    shift_int = SHIFT_MAP_INT[shift_sym]
                    if is_hard:
                        # ハード制約として追加
                        model.Add(shifts[(e_idx, d_idx)] == shift_int)
                    else:
                        # ソフト制約として追加
                        penalty_var = model.NewBoolVar(f'pref_shift_penalty_e{e_idx}_d{d_idx}')
                        # 夜勤希望かそれ以外かでペナルティリストを使い分ける
                        if shift_int == SHIFT_MAP_INT.get('夜'):
                             night_preference_penalties.append(penalty_var)
                        else:
                             # 他のシフト希望は weekday_penalties に追加 (要検討だが一旦)
                             weekday_penalties.append(penalty_var)
                        # シフトが希望通りでない場合にペナルティが発生
                        model.Add(shifts[(e_idx, d_idx)] != shift_int).OnlyEnforceIf(penalty_var)
                        model.Add(shifts[(e_idx, d_idx)] == shift_int).OnlyEnforceIf(penalty_var.Not())
                else:
                    print(f"警告(モデル): 無効または不完全な SPECIFY_DATE_SHIFT ルールをスキップ: {rule}")

            elif rule_type == 'MAX_CONSECUTIVE_WORK':
                max_days = rule.get('max_days')
                is_hard = rule.get('is_hard', True) # is_hard がなければ True (ハード) とする
                rule_key = f"max_work_{e_idx}" # 複数適用防止キー

                # パラメータ検証 (念のため)
                if not (isinstance(max_days, int) and max_days >= 0 and isinstance(is_hard, bool)):
                    print(f"警告(モデル): 無効なパラメータを持つ MAX_CONSECUTIVE_WORK ルールをスキップ: {rule}")
                    continue

                if rule_key not in processed_rule_types:
                    initial_consecutive_work = 0
                    if past_shifts_lookup is not None and emp_id in past_shifts_lookup.index:
                         for i in range(1, max_days + 2):
                              past_date_str = (START_DATE - timedelta(days=i)).strftime('%#m/%#d')
                              if past_date_str in past_shifts_lookup.columns:
                                  past_shift = past_shifts_lookup.loc[emp_id, past_date_str]
                                  if past_shift and past_shift not in ['公', '育休', '病休']:
                                      initial_consecutive_work += 1
                                  else: break
                              else: break

                    # 各日が勤務かどうかのブール変数 (変更なし)
                    is_working = [model.NewBoolVar(f'is_work_r6_e{e_idx}_d{d_idx}') for d_idx in all_days]
                    allowed_tuples = [(s,) for s in WORKING_SHIFTS_INT]
                    for d_idx in all_days:
                         model.AddAllowedAssignments((shifts[(e_idx, d_idx)],), allowed_tuples).OnlyEnforceIf(is_working[d_idx])
                         model.AddForbiddenAssignments((shifts[(e_idx, d_idx)],), allowed_tuples).OnlyEnforceIf(is_working[d_idx].Not())

                    window_size = max_days + 1
                    max_consecutive_work_penalties = [] # ソフト制約用のペナルティリスト

                    for d_start in range(-initial_consecutive_work, num_days - max_days):
                         vars_in_window = []
                         for d_offset in range(window_size):
                              d_current = d_start + d_offset
                              if d_current < 0: continue
                              if d_current >= num_days: break
                              vars_in_window.append(is_working[d_current])

                         window_sum_expr = cp_model.LinearExpr.Sum(vars_in_window)
                         effective_max_days = max_days
                         if d_start < 0:
                              # 開始日より前の期間を含む場合、有効なウィンドウサイズで上限を調整
                              effective_window_size = window_size + d_start
                              if effective_window_size <= 0: continue
                              # effective_max_days = effective_window_size - 1 # これだと常に違反しない？
                              effective_max_days = max(0, effective_window_size - 1) # 0日以上とする
                         
                         if is_hard:
                             # ハード制約: ウィンドウ内の勤務日数が上限以下
                             if effective_max_days < max_days:
                                 model.Add(window_sum_expr <= effective_max_days)
                             else:
                                 model.Add(window_sum_expr <= max_days)
                         else:
                             # ソフト制約: 上限を超えた場合にペナルティ
                             # 超過日数 = max(0, window_sum - effective_max_days)
                             max_possible_excess = window_size # 最大超過日数
                             excess_var = model.NewIntVar(0, max_possible_excess, f'max_work_excess_e{e_idx}_d{d_start}')
                             # window_sum_expr - effective_max_days <= excess_var を表現
                             model.Add(window_sum_expr - effective_max_days <= excess_var)
                             # excess_var >= 0 は NewIntVar で定義済み
                             max_consecutive_work_penalties.append(excess_var)

                    processed_rule_types.add(rule_key) # 処理済みマーク

                    # ソフト制約の場合、ペナルティを目的関数に追加 (後でまとめて行うのでここではリストに追加のみ)
                    # TODO: max_consecutive_work_penalties を目的関数の penalties_with_weights に追加する -> 削除

            elif rule_type == 'FORBID_SHIFT':
                shift_sym = rule.get('shift')
                if shift_sym in SHIFT_MAP_INT:
                    shift_int = SHIFT_MAP_INT[shift_sym]
                    for d_idx in all_days:
                        model.Add(shifts[(e_idx, d_idx)] != shift_int)
                # else: print(...) エラー処理

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
                 is_hard = rule.get('is_hard', True) # is_hard がなければ True (ハード)
                 rule_key = f"total_{e_idx}_{'_'.join(target_shifts_sym)}_{min_count}_{max_count}_{is_hard}"

                 # パラメータ検証 (念のため)
                 if not (isinstance(target_shifts_sym, list) and (min_count is not None or max_count is not None) and isinstance(is_hard, bool)):
                     print(f"警告(モデル): 無効なパラメータを持つ TOTAL_SHIFT_COUNT ルールをスキップ: {rule}")
                     continue

                 if rule_key not in processed_rule_types:
                      target_ints = [SHIFT_MAP_INT[s] for s in target_shifts_sym if s in SHIFT_MAP_INT]
                      if target_ints:
                           count_vars = []
                           allowed_tuples = [(t_int,) for t_int in target_ints]
                           for d_idx in all_days:
                                is_target = model.NewBoolVar(f'is_total_count_e{e_idx}_d{d_idx}_{rule_key[:10]}')
                                model.AddAllowedAssignments((shifts[(e_idx, d_idx)],), allowed_tuples).OnlyEnforceIf(is_target)
                                model.AddForbiddenAssignments((shifts[(e_idx, d_idx)],), allowed_tuples).OnlyEnforceIf(is_target.Not())
                                count_vars.append(is_target)
                           actual_count_expr = cp_model.LinearExpr.Sum(count_vars)

                           if is_hard:
                               # ハード制約
                               if min_count is not None: model.Add(actual_count_expr >= min_count)
                               if max_count is not None: model.Add(actual_count_expr <= max_count)
                           else:
                               # ソフト制約: 目標からの差分をペナルティとする
                               max_possible_deviation = num_days # 最大の差分は期間日数
                               if min_count is not None:
                                   # 不足分 = max(0, min_count - actual_count)
                                   deviation_min = model.NewIntVar(0, max_possible_deviation, f'total_shift_dev_min_e{e_idx}_{rule_key[:5]}')
                                   model.Add(min_count - actual_count_expr <= deviation_min)
                                   total_shift_count_penalties.append(deviation_min)
                               if max_count is not None:
                                   # 超過分 = max(0, actual_count - max_count)
                                   deviation_max = model.NewIntVar(0, max_possible_deviation, f'total_shift_dev_max_e{e_idx}_{rule_key[:5]}')
                                   model.Add(actual_count_expr - max_count <= deviation_max)
                                   total_shift_count_penalties.append(deviation_max)

                           processed_rule_types.add(rule_key)
                      else:
                         print(f"警告(モデル): TOTAL_SHIFT_COUNT の shifts が無効: {rule}")
                 else:
                     print(f"警告(モデル): 無効または重複する TOTAL_SHIFT_COUNT ルール: {rule}")

            elif rule_type == 'MAX_CONSECUTIVE_OFF':
                # グループ指定の最大連休 (個人ルール実装を流用 -> 直接実装に変更)
                group_name = rule.get('employee_group', 'ALL')
                max_off_days = rule.get('max_days')
                is_hard = rule.get('is_hard', True)
                target_employee_indices = get_employees_by_group(employees_df, group_name, emp_id_to_idx)
                rule_key_facility = f"max_off_fac_{group_name}_{max_off_days}_{is_hard}"

                # target_employee_indices が空の場合の警告を追加
                if not target_employee_indices:
                     print(f"警告(施設モデル): MAX_CONSECUTIVE_OFF の対象グループ '{group_name}' が見つかりません。ルールスキップ: {rule}")
                     continue

                if isinstance(max_off_days, int) and max_off_days >= 0 and isinstance(is_hard, bool) and rule_key_facility not in processed_facility_rules:
                    print(f"DEBUG (Facility MAX_CONSECUTIVE_OFF): Applying to group '{group_name}' (indices: {target_employee_indices}) with max_days={max_off_days}, is_hard={is_hard}")
                    for e_idx in target_employee_indices:
                        rule_key_emp = f'max_off_{e_idx}'
                        if rule_key_emp in processed_rule_types: continue # 個人ルール優先
                        
                        # --- add_max_consecutive_off_constraint のロジックをここに展開 ---
                        is_off = [model.NewBoolVar(f'is_off_r_maxoff_fac_e{e_idx}_d{d_idx}') for d_idx in all_days]
                        off_tuples = [(off_int,) for off_int in OFF_SHIFT_INTS]
                        for d_idx in all_days:
                            model.AddAllowedAssignments((shifts[(e_idx, d_idx)],), off_tuples).OnlyEnforceIf(is_off[d_idx])
                            model.AddForbiddenAssignments((shifts[(e_idx, d_idx)],), off_tuples).OnlyEnforceIf(is_off[d_idx].Not())

                        initial_consecutive_off = 0
                        emp_id = emp_idx_to_id.get(e_idx) # emp_id を取得
                        if past_shifts_lookup is not None and emp_id is not None and emp_id in past_shifts_lookup.index:
                            for i in range(1, max_off_days + 2):
                                past_date_str = (START_DATE - timedelta(days=i)).strftime('%#m/%#d')
                                if past_date_str in past_shifts_lookup.columns:
                                    past_shift = past_shifts_lookup.loc[emp_id, past_date_str]
                                    if past_shift and past_shift in SHIFT_MAP_INT and SHIFT_MAP_INT[past_shift] in OFF_SHIFT_INTS:
                                        initial_consecutive_off += 1
                                    else: break
                                else: break

                        window_size = max_off_days + 1
                        for d_start in range(-initial_consecutive_off, num_days - max_off_days):
                            vars_in_window = []
                            for d_offset in range(window_size):
                                d_current = d_start + d_offset
                                if d_current < 0: continue
                                if d_current >= num_days: break
                                vars_in_window.append(is_off[d_current])

                            window_sum_expr = cp_model.LinearExpr.Sum(vars_in_window)
                            effective_max_off_days = max_off_days
                            if d_start < 0:
                                effective_window_size = window_size + d_start
                                if effective_window_size <= 0: continue
                                effective_max_off_days = max(0, effective_window_size - 1)

                            if is_hard:
                                if effective_max_off_days < max_off_days:
                                    model.Add(window_sum_expr <= effective_max_off_days)
                                else:
                                    model.Add(window_sum_expr <= max_off_days)
                            else:
                                max_possible_excess = window_size
                                excess_var = model.NewIntVar(0, max_possible_excess, f'max_off_excess_fac_e{e_idx}_d{d_start}')
                                model.Add(window_sum_expr - effective_max_off_days <= excess_var)
                                max_consecutive_off_penalties.append(excess_var)
                        # --- ロジック展開ここまで ---
                        processed_rule_types.add(rule_key_emp) # 従業員単位でマーク
                    processed_facility_rules.add(rule_key_facility)
                else:
                    print(f"警告(施設モデル): 無効なパラメータまたは重複する MAX_CONSECUTIVE_OFF ルール: {rule}")

            elif rule_type == 'BALANCE_OFF_DAYS':
                group_name = rule.get('employee_group', 'ALL')
                weight = rule.get('weight', 1)
                target_employee_indices = get_employees_by_group(employees_df, group_name, emp_id_to_idx)
                
                if len(target_employee_indices) > 1:
                    num_off_days_vars = {}
                    off_day_int_eq = SHIFT_MAP_INT['公']
                    for e_idx in target_employee_indices:
                        off_count_expr = cp_model.LinearExpr.Sum([shifts[(e_idx, d_idx)] == off_day_int_eq for d_idx in all_days])
                        num_off_days_vars[e_idx] = model.NewIntVar(0, num_days, f'off_count_bal_e{e_idx}')
                        model.Add(num_off_days_vars[e_idx] == off_count_expr)
                    
                    min_off_days = model.NewIntVar(0, num_days, f'min_off_bal_{group_name}')
                    max_off_days = model.NewIntVar(0, num_days, f'max_off_bal_{group_name}')
                    model.AddMinEquality(min_off_days, list(num_off_days_vars.values()))
                    model.AddMaxEquality(max_off_days, list(num_off_days_vars.values()))
                    off_days_difference = model.NewIntVar(0, num_days, f'off_diff_bal_{group_name}')
                    model.Add(off_days_difference == max_off_days - min_off_days)
                    # 重みを考慮してペナルティリストに追加
                    penalty_value = int(round(weight * 100)) if isinstance(weight, (int, float)) else 100
                    balance_off_days_penalties.append(off_days_difference * penalty_value)
                    processed_facility_rules.add(rule_key)
                else:
                    print(f"警告(施設モデル): 対象者が1名以下のため BALANCE_OFF_DAYS ルールはスキップ: {rule}")

            elif rule_type == 'ENFORCE_SHIFT_SEQUENCE': # 施設向け
                group_name = rule.get('employee_group', 'ALL')
                preceding_shift_sym = rule.get('preceding_shift')
                subsequent_shift_sym = rule.get('subsequent_shift')
                is_hard = rule.get('is_hard', True) # デフォルトTrue
                rule_key = f"fac_enforce_seq_{group_name}_{preceding_shift_sym}_{subsequent_shift_sym}_{is_hard}"

                if rule_key not in processed_facility_rules:
                    target_employee_indices = get_employees_by_group(employees_df, group_name, emp_id_to_idx)
                    if not target_employee_indices:
                        print(f"警告(施設モデル): ENFORCE_SHIFT_SEQUENCE の対象グループ '{group_name}' が見つかりません。ルールスキップ: {rule}")
                        # continue #ループ内でないためcontinueは不可
                    else:
                        pre_shift_int = SHIFT_MAP_INT.get(preceding_shift_sym)
                        sub_shift_int = SHIFT_MAP_INT.get(subsequent_shift_sym)

                        if pre_shift_int is not None and sub_shift_int is not None:
                            for e_idx in target_employee_indices:
                                emp_id_current = emp_idx_to_id.get(e_idx)
                                emp_info_current = get_employee_info(employees_df, emp_id_current)
                                if emp_info_current and emp_info_current.get('status') in ['育休', '病休']:
                                    continue
                                for d_idx in range(num_days - 1):
                                    # b_pre is true if shifts[(e_idx, d_idx)] == pre_shift_int
                                    b_pre = model.NewBoolVar(f'fac_enf_seq_pre_e{e_idx}_d{d_idx}_{rule_key[:10]}')
                                    model.Add(shifts[(e_idx, d_idx)] == pre_shift_int).OnlyEnforceIf(b_pre)
                                    model.Add(shifts[(e_idx, d_idx)] != pre_shift_int).OnlyEnforceIf(b_pre.Not())
                                    
                                    # if b_pre is true, then shifts[(e_idx, d_idx + 1)] must be sub_shift_int
                                    if is_hard:
                                        model.Add(shifts[(e_idx, d_idx + 1)] == sub_shift_int).OnlyEnforceIf(b_pre)
                                    else:
                                        # ソフト制約: 違反した場合にペナルティ
                                        b_viol = model.NewBoolVar(f'fac_enf_seq_viol_e{e_idx}_d{d_idx}_{rule_key[:10]}')
                                        # 違反条件: b_pre が True かつ shifts[(e_idx, d_idx + 1)] != sub_shift_int
                                        # b_viol が True <=> 違反
                                        model.Add(shifts[(e_idx, d_idx + 1)] != sub_shift_int).OnlyEnforceIf(b_pre, b_viol)
                                        # b_viol が False なら違反していない (b_pre がFalse か、または シーケンスが守られている)
                                        # 上記の制約だけだと、b_pre=True, shifts==sub の場合に b_viol がTrueにもFalseにもなれる。
                                        # 正しくは、b_viol が True <=> (b_pre AND shifts != sub)
                                        # (b_pre AND shifts != sub) => b_viol  : model.AddImplication(b_pre, model.Implication(shifts[(e,d+1)]!=sub, b_viol) これは複雑
                                        # 直接的に違反変数を定義する
                                        # 違反 = 1 if (先行が一致 AND 後続が不一致) else 0
                                        # penalty_var = model.NewBoolVar(...)
                                        # model.Add(shifts[(e_idx, d_idx)] == pre_shift_int)
                                        # model.Add(shifts[(e_idx, d_idx+1)] != sub_shift_int)
                                        # 上記2つが同時に成り立つ場合に penalty_var を 1 にする ->難しい
                                        # 代わりに、(先行 => 後続) が False の場合にペナルティ
                                        # (A => B) は (not A or B)。この否定は (A and not B)
                                        is_not_subsequent = model.NewBoolVar('')
                                        model.Add(shifts[(e_idx, d_idx+1)] != sub_shift_int).OnlyEnforceIf(is_not_subsequent)
                                        model.Add(shifts[(e_idx, d_idx+1)] == sub_shift_int).OnlyEnforceIf(is_not_subsequent.Not())

                                        # violation = b_pre AND is_not_subsequent
                                        violation_var = model.NewBoolVar(f'fac_enf_seq_v_e{e_idx}_d{d_idx}')
                                        model.AddBoolAnd([b_pre, is_not_subsequent]).OnlyEnforceIf(violation_var)
                                        model.AddImplication(violation_var, b_pre) # if violation then b_pre must be true
                                        model.AddImplication(violation_var, is_not_subsequent) # if violation then is_not_subsequent must be true
                                        # (Converse) If b_pre and is_not_subsequent, then violation_var must be true.
                                        # This is tricky with OnlyEnforceIf for the converse.
                                        # A simpler way for soft (A => B) is to penalize A and Not B.
                                        # Penalty if b_pre is true AND shifts[e,d+1] is NOT sub_shift_int
                                        # Let p be penalty var. p=1 if b_pre and shifts[e,d+1]!=sub_shift_int
                                        # p >= b_pre + (1 if shifts[e,d+1]!=sub_shift_int else 0) - 1
                                        # This is also complex. Let's use a simpler penalty for now if we must.
                                        # The most straightforward way is to add a large cost if is_hard=False and the AddImplication is violated.
                                        # For CpModel, we can rephrase: Add(shifts[(e, d+1)] == sub_shift_int).OnlyEnforceIf(b_pre) is hard.
                                        # For soft, we would typically add a variable to the objective that represents the violation.
                                        # (b_pre implies shifts[e,d+1]==sub_shift_int). Penality if b_pre AND shifts[e,d+1]!=sub_shift_int
                                        # This is equivalent to (NOT b_pre) OR (shifts[e,d+1]==sub_shift_int). Maximize this for all d.
                                        # Or, minimize cases where b_pre AND shifts[e,d+1]!=sub_shift_int.
                                        enf_seq_penalty_var = model.NewBoolVar(f'enf_seq_penalty_e{e_idx}_d{d_idx}_{rule_key[:5]}')
                                        # We want enf_seq_penalty_var to be 1 if (b_pre AND shifts[e,d+1] != sub_shift_int)
                                        # This means (NOT b_pre) OR (shifts[e,d+1] == sub_shift_int) OR enf_seq_penalty_var
                                        model.AddBoolOr([b_pre.Not(), shifts[(e_idx, d_idx+1)] == sub_shift_int, enf_seq_penalty_var])
                                        # And if b_pre and shifts[e,d+1]!=sub_shift_int, then enf_seq_penalty_var must be true.
                                        # (b_pre AND shifts[e,d+1]!=sub_shift_int) IMPLIES enf_seq_penalty_var.
                                        # This is not quite right for penalty. We want to count violations.
                                        # Add a var that is 1 if b_pre is true and shifts[e,d+1] != sub_shift_int
                                        violation = model.NewBoolVar(f'enf_seq_viol_e{e_idx}_d{d_idx}')
                                        model.Add(shifts[(e_idx, d_idx)] == pre_shift_int).OnlyEnforceIf(violation) # if violation, pre must match
                                        model.Add(shifts[(e_idx, d_idx+1)] != sub_shift_int).OnlyEnforceIf(violation) # if violation, sub must not match
                                        # This means violation can only be true if both conditions met.
                                        # We also need: if both conditions met, violation MUST be true.
                                        # model.AddImplication(model.BoolAnd([b_pre, is_not_subsequent_placeholder]), violation) -> BoolAnd not directly available in AddImplication
                                        # Create intermediate for (shifts[e,d+1]!=sub_shift_int)
                                        not_sub_shift = model.NewBoolVar(f'not_sub_e{e_idx}_d{d_idx}')
                                        model.Add(shifts[(e_idx, d_idx+1)] != sub_shift_int).OnlyEnforceIf(not_sub_shift)
                                        model.Add(shifts[(e_idx, d_idx+1)] == sub_shift_int).OnlyEnforceIf(not_sub_shift.Not())
                                        # violation is true if (b_pre AND not_sub_shift)
                                        model.AddMultiplicationEquality(violation, [b_pre, not_sub_shift]) # Product of two bools
                                        enforce_sequence_penalties.append(violation)
                        else:
                            print(f"警告(施設モデル): ENFORCE_SHIFT_SEQUENCE のシフト記号が無効です。ルールスキップ: {rule}")
                    processed_facility_rules.add(rule_key)

            elif rule_type == 'MIN_TOTAL_SHIFT_DAYS':
                group_name = rule.get('employee_group', 'ALL')
                target_shift_sym = rule.get('shift')
                min_days = rule.get('min_count')
                is_hard = rule.get('is_hard', True) # デフォルトTrue
            elif rule_type == 'UNPARSABLE':
                print(f"情報(施設モデル): 処理できないルール: {rule}")
            elif rule_type == 'REQUIRED_STAFFING':
                floor = rule.get('floor', 'ALL')
                target_shift_sym = rule.get('shift')
                date_type = rule.get('date_type')
                min_count = rule.get('min_count')
                is_hard = rule.get('is_hard', True)
                rule_key = f"staffing_{floor}_{target_shift_sym}_{date_type}_{min_count}_{is_hard}"

                if rule_key not in processed_facility_rules:
                    target_shift_int = SHIFT_MAP_INT.get(target_shift_sym)
                    if target_shift_int is None:
                        print(f"警告(施設モデル): REQUIRED_STAFFING のシフト記号 '{target_shift_sym}' が無効です。ルールスキップ: {rule}")
                        continue

                    target_employee_indices = get_employees_by_group(employees_df, "ALL", emp_id_to_idx)
                    if floor != 'ALL':
                        target_employee_indices = [
                            e_idx for e_idx in target_employee_indices
                            if get_employee_info(employees_df, emp_idx_to_id.get(e_idx)).get('担当フロア') == floor
                        ]

                    if not target_employee_indices:
                         print(f"警告(施設モデル): REQUIRED_STAFFING の対象フロア '{floor}' の従業員が見つかりません。ルールスキップ: {rule}")
                         continue

                    for d_idx, current_date in enumerate(date_range):
                        if match_date_type(current_date, date_type, jp_holidays):
                            actual_staff_count_expr = cp_model.LinearExpr.Sum(
                                [shifts[(e_idx, d_idx)] == target_shift_int for e_idx in target_employee_indices]
                            )

                            if is_hard:
                                # ★修正: ハード制約の場合、人数を min_count に一致させる
                                model.Add(actual_staff_count_expr == min_count)
                                # ★削除: is_hard=True の場合の超過ペナルティは不要になる
                            else:
                                # ソフト制約: 不足と超過の両方にペナルティ (既存のまま)
                                max_possible_shortage = min_count
                                shortage_var = model.NewIntVar(0, max_possible_shortage, f'short_staff_s_f{floor}_s{target_shift_sym}_d{d_idx}')
                                model.Add(min_count - actual_staff_count_expr <= shortage_var)
                                total_staffing_penalties.append(shortage_var)

                                max_possible_excess = len(target_employee_indices)
                                excess_var = model.NewIntVar(0, max_possible_excess, f'over_staff_s_f{floor}_s{target_shift_sym}_d{d_idx}')
                                model.Add(actual_staff_count_expr - min_count <= excess_var)
                                over_staffing_penalties.append(excess_var)
                    processed_facility_rules.add(rule_key)
            # else: 未知のルールタイプはパーサーで弾かれるはず

    # <<< ここまで施設全体ルールの処理 >>>

    # <<< 既存の全体ルールのうち、AI解釈に置き換えられないもの >>>
    # 直前勤務 (#3) は個人ルール側で処理される想定
    # 夜勤ローテーション (#5) は ENFORCE_SHIFT_SEQUENCE で代替想定 (現状ハードコード)
    # -> 夜勤ローテのハードコードは残す (ENFORCE_SHIFT_SEQUENCE が facility_rules になければ)
    night_seq_enforced_by_rule = any(r.get('rule_type') == 'ENFORCE_SHIFT_SEQUENCE' and r.get('employee_group') == 'ALL' for r in facility_rules)
    if not night_seq_enforced_by_rule:
        print("Applying hardcoded night rotation rule (no facility rule found).")
    for e_idx in all_employees:
        emp_info = get_employee_info(employees_df, emp_idx_to_id.get(e_idx))
        if emp_info is not None and emp_info.get('status') in ['育休', '病休']: continue
        for d_idx in range(num_days - 1):
            b_night = model.NewBoolVar(f'b_n_e{e_idx}d{d_idx}_hc')
            model.Add(shifts[(e_idx, d_idx)] == SHIFT_MAP_INT['夜']).OnlyEnforceIf(b_night)
            model.Add(shifts[(e_idx, d_idx)] != SHIFT_MAP_INT['夜']).OnlyEnforceIf(b_night.Not())
            model.Add(shifts[(e_idx, d_idx + 1)] == SHIFT_MAP_INT['明']).OnlyEnforceIf(b_night)
            b_ake = model.NewBoolVar(f'b_a_e{e_idx}d{d_idx}_hc')
            model.Add(shifts[(e_idx, d_idx)] == SHIFT_MAP_INT['明']).OnlyEnforceIf(b_ake)
            model.Add(shifts[(e_idx, d_idx)] != SHIFT_MAP_INT['明']).OnlyEnforceIf(b_ake.Not())
            model.Add(shifts[(e_idx, d_idx + 1)] == SHIFT_MAP_INT['公']).OnlyEnforceIf(b_ake)

    # 人員配置基準 (#4) - ハードコード部分をコメントアウト (REQUIRED_STAFFINGルールで代替)
    # personnel_key_map = ...
    # total_required_personnel = ...
    # ... (ループと制約追加)

    # 副主任勤務 (#14) - ハードコード部分をコメントアウト (MIN_ROLE_ON_DUTYルールで代替)
    # vice_manager_indices = ...
    # if vice_manager_indices:
    #    ... (ループと制約追加)

    # 明け人数均等化 (ソフト#3) はスコープ外
    # 応援最小化 (ソフト#2) は目的関数で直接扱う？（現状ハードコード） -> そのまま

    # --- 目的関数 --- 
    objective_terms = []
    # 各ペナルティリスト名と重み
    helping_penalties = list(is_helping_1F_to_2F.values()) + list(is_helping_2F_to_1F.values()) # 辞書の値(BoolVar)をリスト化
    penalties_with_weights = [
        (ab_schedule_penalties, 1),
        (weekday_penalties, 1),
        (night_preference_penalties, 1),
        (max_consecutive_work_penalties, 1),
        (max_consecutive_off_penalties, 1),
        (total_shift_count_penalties, 1),
        (balance_off_days_penalties, 1),
        (ake_count_deviation_penalties, 1),
        (total_staffing_penalties, 100), # 不足ペナルティ (重みを仮に100とする)
        (over_staffing_penalties, 10),   # ★超過ペナルティ (重みを仮に10とする)
        (min_role_penalties, 1),
        (forbid_sequence_penalties, 1),
        (enforce_sequence_penalties, 1),
        (helping_penalties, 1), # ★応援ペナルティを追加 (重みは仮に1)
        (facility_min_total_shift_penalties, 10),
        (facility_max_consecutive_work_penalties, 5),
        # balance_specific_shift_penalties is handled differently as it's already weighted
    ]

    # 目的関数にペナルティ項を追加
    for penalty_list, weight in penalties_with_weights:
         if penalty_list:
             # リスト内の各要素(IntVar or BoolVar)に重みを掛けて合計
             # BoolVarもIntVarと同様にSumできる (True=1, False=0)
             weighted_terms = [term * weight for term in penalty_list]
             objective_terms.append(cp_model.LinearExpr.Sum(weighted_terms))

    # if off_days_difference is not None: # 公休均等化はコメントアウト中
    #     objective_terms.append(off_balance_penalty_weight * off_days_difference)

    if objective_terms:
        model.Minimize(cp_model.LinearExpr.Sum(objective_terms))
        # 目的関数の表示を修正
        print("Objective function set: Minimize Weighted Penalties.")
    else:
        print("No objective function set.")

    print("Constraints added.")
    return model, shifts, employee_ids, date_range 


# --- ヘルパー関数 (新規追加/修正) ---

def match_date_type(target_date: date, date_type: str, jp_holidays: set) -> bool:
    """日付が指定された日付タイプに一致するか判定"""
    if date_type == "ALL": return True
    weekday = target_date.weekday()
    is_holiday = target_date in jp_holidays
    if date_type == "平日": return weekday < 5 and not is_holiday
    if date_type == "休日": return weekday >= 5 or is_holiday # 土日または祝日
    if date_type == "祝日": return is_holiday
    if date_type == "土日": return weekday >= 5
    if date_type == "土日祝": return weekday >= 5 or is_holiday
    try:
        # YYYY-MM-DD形式かチェック
        specific_date = date.fromisoformat(date_type)
        return target_date == specific_date
    except ValueError:
        return False # 不明なタイプ

def get_employees_by_group(employees_df, group_name, emp_id_to_idx):
    """指定されたグループ名に属する従業員のインデックスリストを返す"""
    target_indices = []
    for idx, eid in emp_id_to_idx.items():
        emp_info = get_employee_info(employees_df, eid)
        # ここも is not None でチェック (前回修正済みのはず)
        if emp_info is None: continue

        status = emp_info.get('status')
        if status in ['育休', '病休']: continue

        if group_name == "ALL":
            target_indices.append(idx)
        elif group_name == "常勤":
            if emp_info.get('常勤/パート') == '常勤':
                 target_indices.append(idx)
        elif group_name == "パート":
            if 'パート' in str(emp_info.get('常勤/パート')):
                 target_indices.append(idx)
        else:
            # 役職名でフィルタリング
            if emp_info.get('役職') == group_name:
                target_indices.append(idx)
    
    # グループが見つからなかった場合の警告（任意）
    if not target_indices:
         if group_name not in ["ALL", "常勤", "パート"]:
             # ALL/常勤/パート以外で見つからない場合は役職名の可能性が高い
              print(f"警告: 従業員情報にグループ/役職名 '{group_name}' が見つからないか、対象者がいません。")
         elif group_name in ["常勤", "パート"]:
              print(f"警告: グループ '{group_name}' に属する有効な従業員が見つかりません。")

    return target_indices

# add_max_consecutive_off_constraint 関数定義を削除
# def add_max_consecutive_off_constraint(...):
#    ... 