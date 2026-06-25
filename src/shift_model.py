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
    # --- DEBUG START: emp_id_to_idx の内容確認 ---
    print(f"DEBUG SHIFT_MODEL (Initial): emp_id_to_idx type: {type(emp_id_to_idx)}, size: {len(emp_id_to_idx)}. First 3: {list(emp_id_to_idx.items())[:3]}")
    # --- DEBUG END ---
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

    # ペナルティリストの初期化 (ここにあるべき)
    ab_schedule_penalties = []
    weekday_penalties = []
    night_preference_penalties = []
    ake_count_deviation_penalties = []
    max_consecutive_work_penalties = []
    max_consecutive_off_penalties = []
    total_shift_count_penalties = []
    balance_off_days_penalties = []
    total_staffing_penalties = [] 
    over_staffing_penalties = []  
    min_role_penalties = [] 
    forbid_sequence_penalties = [] 
    enforce_sequence_penalties = [] 
    balance_specific_shift_penalties = [] 
    facility_min_total_shift_penalties = [] 
    facility_max_consecutive_work_penalties = [] 
    # off_days_difference = None # これはペナルティリストではない
    # full_time_employee_indices = [] # これもペナルティリストではない
    # num_off_days_vars = {} # これもペナルティリストではない

    # <<< 個人ルールの処理 >>>
    print("Processing personal rules...")
    # --- DEBUG START: 個人ルールループ前の emp_id_to_idx 確認 ---
    print(f"DEBUG SHIFT_MODEL (Before Personal Loop): emp_id_to_idx type: {type(emp_id_to_idx)}, size: {len(emp_id_to_idx)}. First 3: {list(emp_id_to_idx.items())[:3]}")
    # --- DEBUG END ---
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

        for rule in employee_specific_rules[e_idx]:
            rule_type = rule.get('rule_type')

            current_status = emp_info.get('status')
            if current_status in ['育休', '病休']:
                 status_int = SHIFT_MAP_INT.get(current_status)
                 if status_int is not None:
                     for d_idx in all_days: model.Add(shifts[(e_idx, d_idx)] == status_int)
                 continue 
            if SHIFT_MAP_INT.get('育休') is not None:
                 for d_idx in all_days: model.Add(shifts[(e_idx, d_idx)] != SHIFT_MAP_INT['育休'])

            if rule_type == 'SPECIFY_DATE_SHIFT':
                target_date = rule.get('date')
                shift_sym = rule.get('shift')
                is_hard = rule.get('is_hard', True) 
                if target_date in date_to_d_idx and shift_sym in SHIFT_MAP_INT and isinstance(is_hard, bool):
                    d_idx = date_to_d_idx[target_date]
                    shift_int = SHIFT_MAP_INT[shift_sym]
                    if is_hard:
                        model.Add(shifts[(e_idx, d_idx)] == shift_int)
                    else:
                        penalty_var = model.NewBoolVar(f'pref_shift_penalty_e{e_idx}_d{d_idx}')
                        if shift_int == SHIFT_MAP_INT.get('夜'):
                             night_preference_penalties.append(penalty_var)
                        else:
                             weekday_penalties.append(penalty_var)
                        model.Add(shifts[(e_idx, d_idx)] != shift_int).OnlyEnforceIf(penalty_var)
                        model.Add(shifts[(e_idx, d_idx)] == shift_int).OnlyEnforceIf(penalty_var.Not())
                else:
                    print(f"警告(モデル): 無効または不完全な SPECIFY_DATE_SHIFT ルールをスキップ: {rule}")

            elif rule_type == 'MAX_CONSECUTIVE_WORK': # 個人ルール専用 (employee_group を持たないもの)
                if 'employee_group' not in rule: # これで個人用と施設用を区別
                max_days = rule.get('max_days')
                    is_hard = rule.get('is_hard', True) 
                    rule_key = f"max_work_{e_idx}"
                if not (isinstance(max_days, int) and max_days >= 0 and isinstance(is_hard, bool)):
                        print(f"警告(モデル): 無効なパラメータを持つ個人の MAX_CONSECUTIVE_WORK ルールをスキップ: {rule}")
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
                    is_working = [model.NewBoolVar(f'is_work_r6_e{e_idx}_d{d_idx}') for d_idx in all_days]
                    allowed_tuples = [(s,) for s in WORKING_SHIFTS_INT]
                    for d_idx in all_days:
                         model.AddAllowedAssignments((shifts[(e_idx, d_idx)],), allowed_tuples).OnlyEnforceIf(is_working[d_idx])
                         model.AddForbiddenAssignments((shifts[(e_idx, d_idx)],), allowed_tuples).OnlyEnforceIf(is_working[d_idx].Not())
                    window_size = max_days + 1
                        # max_consecutive_work_penalties = [] # リストの初期化場所注意
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
                              effective_window_size = window_size + d_start
                              if effective_window_size <= 0: continue
                                  effective_max_days = max(0, effective_window_size - 1)
                         if is_hard:
                             if effective_max_days < max_days:
                                 model.Add(window_sum_expr <= effective_max_days)
                             else:
                                 model.Add(window_sum_expr <= max_days)
                         else:
                                 max_possible_excess = window_size 
                             excess_var = model.NewIntVar(0, max_possible_excess, f'max_work_excess_e{e_idx}_d{d_start}')
                             model.Add(window_sum_expr - effective_max_days <= excess_var)
                             max_consecutive_work_penalties.append(excess_var)
                        processed_rule_types.add(rule_key)

            elif rule_type == 'FORBID_SHIFT':
                shift_sym = rule.get('shift')
                if shift_sym in SHIFT_MAP_INT:
                    shift_int = SHIFT_MAP_INT[shift_sym]
                    for d_idx in all_days:
                        model.Add(shifts[(e_idx, d_idx)] != shift_int)

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
                    processed_rule_types.add(f"combo_{e2_idx}_{emp_id}_{shift_sym}")

            elif rule_type == 'ALLOW_ONLY_SHIFTS':
                allowed_shifts_sym = rule.get('allowed_shifts')
                if isinstance(allowed_shifts_sym, list) and f'allow_{e_idx}' not in processed_rule_types:
                    allowed_ints = [SHIFT_MAP_INT[s] for s in allowed_shifts_sym if s in SHIFT_MAP_INT]
                    all_ints = list(SHIFT_MAP_INT.values())
                    forbidden_ints = [
                        i for i in all_ints 
                        if i not in allowed_ints and 
                           i != SHIFT_MAP_INT.get('育休') and
                           i != SHIFT_MAP_INT.get('公') 
                    ]
                    if forbidden_ints:
                         for d_idx in all_days:
                              model.AddForbiddenAssignments((shifts[(e_idx, d_idx)],), [(f_int,) for f_int in forbidden_ints])
                    processed_rule_types.add(f'allow_{e_idx}')

            elif rule_type == 'TOTAL_SHIFT_COUNT':
                 target_shifts_sym = rule.get('shifts')
                 min_count = rule.get('min')
                 max_count = rule.get('max')
                 is_hard = rule.get('is_hard', True) 
                 rule_key = f"total_{e_idx}_{'_'.join(target_shifts_sym)}_{min_count}_{max_count}_{is_hard}"
                 if not (isinstance(target_shifts_sym, list) and (min_count is not None or max_count is not None) and isinstance(is_hard, bool)):
                     print(f"警告(モデル): 無効なパラメータを持つ TOTAL_SHIFT_COUNT ルールをスキップ: {rule}")
                     continue
                 if rule_key not in processed_rule_types:
                      target_ints = [SHIFT_MAP_INT[s] for s in target_shifts_sym if s in SHIFT_MAP_INT]
                      if target_ints:
                           count_vars = []
                           allowed_tuples_total = [(t_int,) for t_int in target_ints] # 変数名変更
                           for d_idx in all_days:
                                is_target = model.NewBoolVar(f'is_total_count_e{e_idx}_d{d_idx}_{rule_key[:10]}')
                                model.AddAllowedAssignments((shifts[(e_idx, d_idx)],), allowed_tuples_total).OnlyEnforceIf(is_target)
                                model.AddForbiddenAssignments((shifts[(e_idx, d_idx)],), allowed_tuples_total).OnlyEnforceIf(is_target.Not())
                                count_vars.append(is_target)
                           actual_count_expr = cp_model.LinearExpr.Sum(count_vars)
                           if is_hard:
                               if min_count is not None: model.Add(actual_count_expr >= min_count)
                               if max_count is not None: model.Add(actual_count_expr <= max_count)
                           else:
                               max_possible_deviation = num_days
                               if min_count is not None:
                                   deviation_min = model.NewIntVar(0, max_possible_deviation, f'total_shift_dev_min_e{e_idx}_{rule_key[:5]}')
                                   model.Add(min_count - actual_count_expr <= deviation_min)
                                   total_shift_count_penalties.append(deviation_min)
                               if max_count is not None:
                                   deviation_max = model.NewIntVar(0, max_possible_deviation, f'total_shift_dev_max_e{e_idx}_{rule_key[:5]}')
                                   model.Add(actual_count_expr - max_count <= deviation_max)
                                   total_shift_count_penalties.append(deviation_max)
                           processed_rule_types.add(rule_key)
                      else:
                         print(f"警告(モデル): TOTAL_SHIFT_COUNT の shifts が無効: {rule}")
                 # else: # 重複または無効なTOTAL_SHIFT_COUNTルール（コメントアウトされていた箇所）
                 #    print(f"警告(モデル): 無効または重複する TOTAL_SHIFT_COUNT ルール: {rule}")

            elif rule_type == 'MAX_CONSECUTIVE_OFF': 
                if 'employee_group' not in rule: # 個人用
                max_off_days = rule.get('max_days')
                is_hard = rule.get('is_hard', True)
                    rule_key = f"max_off_{e_idx}" 
                if rule_key not in processed_rule_types and isinstance(max_off_days, int) and max_off_days >= 0:
                    is_off_personal = [model.NewBoolVar(f'is_off_pers_e{e_idx}_d{d_idx}') for d_idx in all_days]
                    off_tuples_personal = [(off_int,) for off_int in OFF_SHIFT_INTS]
                    for d_idx in all_days:
                        model.AddAllowedAssignments((shifts[(e_idx, d_idx)],), off_tuples_personal).OnlyEnforceIf(is_off_personal[d_idx])
                        model.AddForbiddenAssignments((shifts[(e_idx, d_idx)],), off_tuples_personal).OnlyEnforceIf(is_off_personal[d_idx].Not())
                    initial_consecutive_off = 0
                    if past_shifts_lookup is not None and emp_id in past_shifts_lookup.index:
                        for i in range(1, max_off_days + 2):
                            past_date_str = (START_DATE - timedelta(days=i)).strftime('%#m/%#d')
                            if past_date_str in past_shifts_lookup.columns:
                                past_shift = past_shifts_lookup.loc[emp_id, past_date_str]
                                if past_shift and past_shift in SHIFT_MAP_INT and SHIFT_MAP_INT[past_shift] in OFF_SHIFT_INTS:
                                    initial_consecutive_off += 1
                                else:
                                    break
                            else:
                                break
                        window_size_off = max_off_days + 1 # 変数名変更
                    for d_start in range(-initial_consecutive_off, num_days - max_off_days):
                            vars_in_window_off = [] # 変数名変更
                            for d_offset in range(window_size_off):
                            d_current = d_start + d_offset
                            if d_current < 0: continue
                            if d_current >= num_days: break
                                vars_in_window_off.append(is_off_personal[d_current])
                            window_sum_expr_off = cp_model.LinearExpr.Sum(vars_in_window_off) # 変数名変更
                        effective_max_off = max_off_days
                        if d_start < 0:
                                effective_window_size_off = window_size_off + d_start # 変数名変更
                                if effective_window_size_off <=0: continue
                                effective_max_off = max(0, effective_window_size_off -1)
                        if is_hard:
                            if effective_max_off < max_off_days:
                                    model.Add(window_sum_expr_off <= effective_max_off)
                                else:
                                    model.Add(window_sum_expr_off <= max_off_days)
                            else:
                                max_possible_excess_off = window_size_off
                            excess_off_var = model.NewIntVar(0, max_possible_excess_off, f'max_pers_off_excess_e{e_idx}_d{d_start}')
                                model.Add(window_sum_expr_off - effective_max_off <= excess_off_var)
                            max_consecutive_off_penalties.append(excess_off_var)
                    processed_rule_types.add(rule_key)
                elif rule_key in processed_rule_types:
                    print(f"情報(モデル): MAX_CONSECUTIVE_OFF (個人) ルールは既に処理済み: {emp_id}")
                else:
                    print(f"警告(モデル): 無効なパラメータを持つ MAX_CONSECUTIVE_OFF (個人) ルールをスキップ: {rule}")

            elif rule_type == 'PREFER_WEEKDAY_SHIFT':
                weekday = rule.get('weekday') 
                shift_sym = rule.get('shift')
                is_hard = rule.get('is_hard', False) 
                weight = rule.get('weight', 1) 
                rule_key = f"pref_weekday_{e_idx}_{weekday}_{shift_sym}_{is_hard}"
                if rule_key not in processed_rule_types and isinstance(weekday, int) and 0 <= weekday <= 6 and shift_sym in SHIFT_MAP_INT:
                    shift_int = SHIFT_MAP_INT[shift_sym]
                    for d_idx in all_days:
                        if date_range[d_idx].weekday() == weekday:
                            if is_hard:
                                model.Add(shifts[(e_idx, d_idx)] == shift_int)
                            else:
                                penalty_var = model.NewBoolVar(f'pref_weekday_penalty_e{e_idx}_d{d_idx}_w{weekday}_s{shift_sym}')
                                model.Add(shifts[(e_idx, d_idx)] != shift_int).OnlyEnforceIf(penalty_var)
                                model.Add(shifts[(e_idx, d_idx)] == shift_int).OnlyEnforceIf(penalty_var.Not())
                                weekday_penalties.append(penalty_var * int(weight))
                    processed_rule_types.add(rule_key)
                elif rule_key in processed_rule_types:
                    print(f"情報(モデル): PREFER_WEEKDAY_SHIFT ルールは既に処理済み: {emp_id}, weekday={weekday}, shift={shift_sym}")
                else:
                    print(f"警告(モデル): 無効なパラメータを持つ PREFER_WEEKDAY_SHIFT ルールをスキップ: {rule}")

            elif rule_type == 'ENFORCE_SHIFT_SEQUENCE':
                if 'employee_group' not in rule: # 個人用
                preceding_shift_sym = rule.get('preceding_shift')
                subsequent_shift_sym = rule.get('subsequent_shift')
                is_hard = rule.get('is_hard', True)
                    rule_key_personal_enforce = f"enforce_seq_personal_{e_idx}_{preceding_shift_sym}_{subsequent_shift_sym}"
                    if rule_key_personal_enforce not in processed_rule_types and preceding_shift_sym in SHIFT_MAP_INT and subsequent_shift_sym in SHIFT_MAP_INT:
                    pre_shift_int = SHIFT_MAP_INT[preceding_shift_sym]
                    sub_shift_int = SHIFT_MAP_INT[subsequent_shift_sym]
                    for d_idx in range(num_days - 1):
                            b_pre = model.NewBoolVar(f'eseq_pre_pers_e{e_idx}_d{d_idx}')
                        model.Add(shifts[(e_idx, d_idx)] == pre_shift_int).OnlyEnforceIf(b_pre)
                        model.Add(shifts[(e_idx, d_idx)] != pre_shift_int).OnlyEnforceIf(b_pre.Not())
                        if is_hard:
                            model.Add(shifts[(e_idx, d_idx + 1)] == sub_shift_int).OnlyEnforceIf(b_pre)
                        else:
                                violation = model.NewBoolVar(f'eseq_viol_pers_e{e_idx}_d{d_idx}')
                                not_sub_shift = model.NewBoolVar(f'eseq_not_sub_pers_e{e_idx}_d{d_idx}')
                            model.Add(shifts[(e_idx, d_idx+1)] != sub_shift_int).OnlyEnforceIf(not_sub_shift)
                            model.Add(shifts[(e_idx, d_idx+1)] == sub_shift_int).OnlyEnforceIf(not_sub_shift.Not())
                            model.AddMultiplicationEquality(violation, [b_pre, not_sub_shift])
                            enforce_sequence_penalties.append(violation)
                        processed_rule_types.add(rule_key_personal_enforce)

            elif rule_type == 'FORBID_SHIFT_SEQUENCE':
                if 'employee_group' not in rule: # 個人用
                    preceding_shift_sym = rule.get('preceding_shift')
                    subsequent_shift_sym = rule.get('subsequent_shift')
                    is_hard = rule.get('is_hard', True)
                    rule_key_personal_forbid = f"forbid_seq_personal_{e_idx}_{preceding_shift_sym}_{subsequent_shift_sym}"
                    if rule_key_personal_forbid not in processed_rule_types and preceding_shift_sym in SHIFT_MAP_INT and subsequent_shift_sym in SHIFT_MAP_INT:
                        pre_shift_int = SHIFT_MAP_INT[preceding_shift_sym]
                        sub_shift_int = SHIFT_MAP_INT[subsequent_shift_sym]
                        for d_idx in range(num_days - 1):
                            if is_hard:
                                b_pre_match = model.NewBoolVar(f'fseq_pre_pers_e{e_idx}_d{d_idx}')
                                b_sub_match = model.NewBoolVar(f'fseq_sub_pers_e{e_idx}_d{d_idx}')
                                model.Add(shifts[(e_idx, d_idx)] == pre_shift_int).OnlyEnforceIf(b_pre_match)
                                model.Add(shifts[(e_idx, d_idx)] != pre_shift_int).OnlyEnforceIf(b_pre_match.Not())
                                model.Add(shifts[(e_idx, d_idx + 1)] == sub_shift_int).OnlyEnforceIf(b_sub_match)
                                model.Add(shifts[(e_idx, d_idx + 1)] != sub_shift_int).OnlyEnforceIf(b_sub_match.Not())
                                model.AddBoolOr([b_pre_match.Not(), b_sub_match.Not()])
                else:
                                violation_var = model.NewBoolVar(f'fseq_viol_pers_e{e_idx}_d{d_idx}')
                                lit_pre_eq = model.NewBoolVar(f'fseq_lit_pre_pers_e{e_idx}_d{d_idx}')
                                model.Add(shifts[(e_idx, d_idx)] == pre_shift_int).OnlyEnforceIf(lit_pre_eq)
                                model.Add(shifts[(e_idx, d_idx)] != pre_shift_int).OnlyEnforceIf(lit_pre_eq.Not())
                                lit_sub_eq = model.NewBoolVar(f'fseq_lit_sub_pers_e{e_idx}_d{d_idx}')
                                model.Add(shifts[(e_idx, d_idx + 1)] == sub_shift_int).OnlyEnforceIf(lit_sub_eq)
                                model.Add(shifts[(e_idx, d_idx + 1)] != sub_shift_int).OnlyEnforceIf(lit_sub_eq.Not())
                                model.AddBoolAnd([lit_pre_eq, lit_sub_eq]).OnlyEnforceIf(violation_var)
                                model.AddImplication(violation_var.Not(), model.BoolOr([lit_pre_eq.Not(), lit_sub_eq.Not()]))
                                forbid_sequence_penalties.append(violation_var)
                        processed_rule_types.add(rule_key_personal_forbid)
            
            elif rule_type == 'UNPARSABLE':
                print(f"情報(個人モデル): 処理できない個人ルール: {rule}")

    # --- DEBUG START: 個人ルールループ後の emp_id_to_idx 確認 ---
    print(f"DEBUG SHIFT_MODEL (After Personal Loop): emp_id_to_idx type: {type(emp_id_to_idx)}, size: {len(emp_id_to_idx)}. First 3: {list(emp_id_to_idx.items())[:3]}")
    # --- DEBUG END ---
    # <<< ここまで個人ルールの処理 >>>

    # <<< 施設全体のルールの処理 >>>
    print("Processing facility rules...")
    processed_facility_rules = set()

    # --- DEBUG START: facility_rulesの内容を確認 ---
    print(f"DEBUG: Content of facility_rules list before loop: {facility_rules}")
    # --- DEBUG START: emp_id_to_idx in facility rule loop ---
    # print(f"DEBUG (Facility Loop - Before Individual Rule Processing): emp_id_to_idx type: {type(emp_id_to_idx)}, size: {len(emp_id_to_idx)}. First 3 items (if any): {list(emp_id_to_idx.items())[:3]}") # これは前回のでOK
    # --- DEBUG END ---

    for rule in facility_rules:
        structured_data = rule.get('structured_data')
        if not isinstance(structured_data, dict):
            print(f"警告(施設モデル): ルールの structured_data が辞書形式ではありません。ルールをスキップ: {rule}")
            continue
        
        rule_type = structured_data.get('rule_type') 

        # print(f"DEBUG: Processing facility rule with type: {rule_type} - Full rule (structured part): {structured_data}") # これはログが長くなるので一旦コメントアウト
        
        if rule_type == 'MIN_TOTAL_SHIFT_DAYS':
            group_name = structured_data.get('employee_group') 
            target_shift_sym = structured_data.get('shift')
            min_days = structured_data.get('min_count')
            is_hard = structured_data.get('is_hard', True)
                rule_key = f"facility_min_total_days_{group_name}_{target_shift_sym}_{min_days}_{is_hard}"

            if rule_key not in processed_facility_rules:
                print(f"DEBUG SHIFT_MODEL: About to call get_employees_by_group for MIN_TOTAL_SHIFT_DAYS. emp_id_to_idx is: {list(emp_id_to_idx.items())[:5]}") # ★追加
                    target_employee_indices = get_employees_by_group(employees_df, group_name, emp_id_to_idx)
                    target_shift_int = SHIFT_MAP_INT.get(target_shift_sym)

                    if not target_employee_indices:
                    print(f"警告(施設モデル): MIN_TOTAL_SHIFT_DAYS の対象グループ '{group_name}' が見つかりません。ルールスキップ: {structured_data}")
                    elif target_shift_int is None:
                    print(f"警告(施設モデル): MIN_TOTAL_SHIFT_DAYS のシフト記号 '{target_shift_sym}' が無効です。ルールスキップ: {structured_data}")
                    elif not isinstance(min_days, int) or min_days < 0:
                    print(f"警告(施設モデル): MIN_TOTAL_SHIFT_DAYS の min_count '{min_days}' が無効です。ルールスキップ: {structured_data}")
                    else:
                    for e_idx_facility in target_employee_indices:
                        emp_id_current = emp_idx_to_id.get(e_idx_facility)
                            emp_info_current = get_employee_info(employees_df, emp_id_current)
                            if emp_info_current and emp_info_current.get('status') in ['育休', '病休']:
                            # print(f"DEBUG (Facility Loop - Add): EMP {emp_id_current} is on leave, skipping MIN_TOTAL_SHIFT_DAYS for them.") # 詳細デバッグはコメントアウト
                            continue
                            actual_shift_count_expr = cp_model.LinearExpr.Sum(
                                [shifts[(e_idx_facility, d_idx)] == target_shift_int for d_idx in all_days]
                            )
                            if is_hard:
                            # print(f"DEBUG (Facility Loop - Add): Adding HARD MIN_TOTAL_SHIFT_DAYS for EMP {emp_id_current} (idx {e_idx_facility}): min {min_days} of shift '{target_shift_sym}'") # 詳細デバッグはコメントアウト
                                model.Add(actual_shift_count_expr >= min_days)
                            else:
                            # print(f"DEBUG (Facility Loop - Add): Adding SOFT MIN_TOTAL_SHIFT_DAYS for EMP {emp_id_current} (idx {e_idx_facility}): min {min_days} of shift '{target_shift_sym}'") # 詳細デバッグはコメントアウト
                                shortage_var = model.NewIntVar(0, min_days, f'fac_min_total_short_e{e_idx_facility}_s{target_shift_sym}')
                                model.Add(min_days - actual_shift_count_expr <= shortage_var)
                                facility_min_total_shift_penalties.append(shortage_var)
                        processed_facility_rules.add(rule_key)
            
            elif rule_type == 'REQUIRED_STAFFING':
            floor = structured_data.get('floor', 'ALL')
            target_shift_sym = structured_data.get('shift')
            date_type_str = structured_data.get('date_type') 
            min_count = structured_data.get('min_count')
            is_hard = structured_data.get('is_hard', True)
            rule_key = f"staffing_{floor}_{target_shift_sym}_{date_type_str}_{min_count}_{is_hard}"

                if rule_key not in processed_facility_rules:
                    target_shift_int = SHIFT_MAP_INT.get(target_shift_sym)
                    if target_shift_int is None:
                    print(f"警告(施設モデル): REQUIRED_STAFFING のシフト記号 '{target_shift_sym}' が無効です。ルールスキップ: {structured_data}")
                        continue
                print(f"DEBUG SHIFT_MODEL: About to call get_employees_by_group for REQUIRED_STAFFING (ALL). emp_id_to_idx is: {list(emp_id_to_idx.items())[:5]}") # ★追加
                all_relevant_employees_indices = get_employees_by_group(employees_df, "ALL", emp_id_to_idx)
                target_employee_indices_for_floor = []
                if floor == 'ALL':
                    target_employee_indices_for_floor = all_relevant_employees_indices
                else:
                    for e_idx_staffing in all_relevant_employees_indices:
                        emp_info_staffing = get_employee_info(employees_df, emp_idx_to_id.get(e_idx_staffing))
                        if emp_info_staffing and emp_info_staffing.get('担当フロア') == floor:
                            target_employee_indices_for_floor.append(e_idx_staffing)
                if not target_employee_indices_for_floor:
                     print(f"警告(施設モデル): REQUIRED_STAFFING の対象フロア '{floor}' の従業員が見つかりません。ルールスキップ: {structured_data}")
                         continue
                for d_idx, current_date_obj in enumerate(date_range): 
                    if match_date_type(current_date_obj, date_type_str, jp_holidays):
                            actual_staff_count_expr = cp_model.LinearExpr.Sum(
                            [shifts[(e_idx_s, d_idx)] == target_shift_int for e_idx_s in target_employee_indices_for_floor]
                            )
                            if is_hard:
                                model.Add(actual_staff_count_expr == min_count)
                            else:
                                max_possible_shortage = min_count
                            shortage_var = model.NewIntVar(0, max_possible_shortage, f'short_staff_f{floor}_s{target_shift_sym}_d{d_idx}')
                                model.Add(min_count - actual_staff_count_expr <= shortage_var)
                                total_staffing_penalties.append(shortage_var)
                            max_possible_excess = len(target_employee_indices_for_floor)
                            excess_var = model.NewIntVar(0, max_possible_excess, f'over_staff_f{floor}_s{target_shift_sym}_d{d_idx}')
                                model.Add(actual_staff_count_expr - min_count <= excess_var)
                                over_staffing_penalties.append(excess_var)
                    processed_facility_rules.add(rule_key)

        elif rule_type == 'UNPARSABLE': 
            print(f"情報(施設モデル): 処理できない施設ルール(UNPARSABLE): {structured_data.get('original_text')}")
        
        # 他の施設ルール (MAX_CONSECUTIVE_WORK, ENFORCE_SHIFT_SEQUENCE など) は後続のステップでここに追加します。

    # <<< ここまで施設全体のルールの処理 >>>

    # <<< 既存の全体ルールのうち、AI解釈に置き換えられないもの (ハードコード部分) >>>
    # 夜勤ローテーション (夜勤→明→公) は、施設ルールで ENFORCE_SHIFT_SEQUENCE が ALL で定義されていなければハードコード適用
    night_seq_rule_found_in_facility = any(
        r.get('rule_type') == 'ENFORCE_SHIFT_SEQUENCE' and
        r.get('employee_group') == 'ALL' and
        r.get('preceding_shift') == '夜' and r.get('subsequent_shift') == '明' and r.get('is_hard') == True
        for r in facility_rules
    ) and any(
        r.get('rule_type') == 'ENFORCE_SHIFT_SEQUENCE' and
        r.get('employee_group') == 'ALL' and
        r.get('preceding_shift') == '明' and r.get('subsequent_shift') == '公' and r.get('is_hard') == True
        for r in facility_rules
    )

    if not night_seq_rule_found_in_facility:
        print("Applying hardcoded night rotation rule (night->ake->off) as no overriding facility rule found.")
    for e_idx in all_employees:
        emp_info = get_employee_info(employees_df, emp_idx_to_id.get(e_idx))
        if emp_info is not None and emp_info.get('status') in ['育休', '病休']: continue
        for d_idx in range(num_days - 1):
                # 夜勤 -> 明け
            b_night = model.NewBoolVar(f'b_n_e{e_idx}d{d_idx}_hc')
            model.Add(shifts[(e_idx, d_idx)] == SHIFT_MAP_INT['夜']).OnlyEnforceIf(b_night)
            model.Add(shifts[(e_idx, d_idx)] != SHIFT_MAP_INT['夜']).OnlyEnforceIf(b_night.Not())
            model.Add(shifts[(e_idx, d_idx + 1)] == SHIFT_MAP_INT['明']).OnlyEnforceIf(b_night)
                # 明け -> 公休 (num_days - 2 までしか見れないので注意)
                if d_idx < num_days - 2:
                    b_ake = model.NewBoolVar(f'b_a_e{e_idx}d{d_idx}_hc') # d_idx は明けの日
                    model.Add(shifts[(e_idx, d_idx + 1)] == SHIFT_MAP_INT['明']).OnlyEnforceIf(b_ake)
                    model.Add(shifts[(e_idx, d_idx + 1)] != SHIFT_MAP_INT['明']).OnlyEnforceIf(b_ake.Not())
                    model.Add(shifts[(e_idx, d_idx + 2)] == SHIFT_MAP_INT['公']).OnlyEnforceIf(b_ake)
    else:
        print("Hardcoded night rotation rule (night->ake->off) is SKIPPED as facility rule for it exists.")


    # --- 目的関数 --- 
    objective_terms = []
    helping_penalties = list(is_helping_1F_to_2F.values()) + list(is_helping_2F_to_1F.values()) # 辞書の値(BoolVar)をリスト化
    penalties_with_weights = [
        (ab_schedule_penalties, 1), # これは現状使われていないはず
        (weekday_penalties, 1),
        (night_preference_penalties, 1),
        (max_consecutive_work_penalties, 1), # 個人ソフト制約の超過勤務ペナルティ
        (max_consecutive_off_penalties, 1),  # 個人ソフト制約の超過休みペナルティ
        (total_shift_count_penalties, 1),    # 個人ソフト制約の総日数不足/超過ペナルティ
        (balance_off_days_penalties, 1),     # 施設ソフト制約の公休均等化ペナルティ (重みはここで乗算済みのはず)
        (ake_count_deviation_penalties, 1),  # これは現状使われていないはず
        (total_staffing_penalties, 100),     # 施設ソフト制約の人員不足ペナルティ
        (over_staffing_penalties, 10),       # 施設ソフト制約の人員超過ペナルティ
        (min_role_penalties, 50),            # 施設ソフト制約の役割最低出勤不足ペナルティ (重み調整)
        (forbid_sequence_penalties, 5),      # 禁止シーケンス違反ペナルティ (重み調整)
        (enforce_sequence_penalties, 5),     # 強制シーケンス違反ペナルティ (重み調整)
        (helping_penalties, 1),              # 応援ペナルティ
        (facility_min_total_shift_penalties, 10), # 施設ソフト制約の総日数不足ペナルティ
        (facility_max_consecutive_work_penalties, 5), # 施設ソフト制約の連続勤務超過ペナルティ
        (balance_specific_shift_penalties, 1) # これは重み付け済みのIntVarが直接入る想定
    ]

    # 目的関数にペナルティ項を追加
    for penalty_list, weight in penalties_with_weights:
         if penalty_list:
             # リスト内の各要素(IntVar or BoolVar)に重みを掛けて合計
             # BoolVarもIntVarと同様にSumできる (True=1, False=0)
             weighted_terms = [term * weight for term in penalty_list]
             objective_terms.append(cp_model.LinearExpr.Sum(weighted_terms))

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
    # --- DEBUG START: get_employees_by_group --- 
    print(f"DEBUG (get_employees_by_group): Called with group_name='{group_name}'")
    print(f"DEBUG (get_employees_by_group): employees_df columns: {employees_df.columns.tolist()}")
    # --- DEBUG END ---

    for idx, eid in emp_id_to_idx.items(): # ここは emp_id_to_idx を使うべき (DataFrameのインデックスではない)
        emp_info = get_employee_info(employees_df, eid)
        if emp_info is None: 
            # print(f"DEBUG (get_employees_by_group): emp_info is None for eid {eid}") # 必要ならコメント解除
            continue

        # --- DEBUG START: emp_infoの内容確認 (最初の数名分など) ---
        if idx < 3: # 例えば最初の3件だけ表示 (ログが長くなりすぎないように)
            print(f"DEBUG (get_employees_by_group): eid={eid}, emp_info='{emp_info}', target_group='{group_name}'")
        # --- DEBUG END ---

        status = emp_info.get('status')
        if status in ['育休', '病休']: 
            # print(f"DEBUG (get_employees_by_group): eid {eid} is on leave.") # 必要ならコメント解除
            continue

        if group_name == "ALL":
            target_indices.append(idx)
        elif group_name == "常勤":
            # print(f"DEBUG (get_employees_by_group): Checking 常勤 for eid {eid}: value is '{emp_info.get('常勤/パート')}'") # 必要ならコメント解除
            if emp_info.get('常勤/パート') == '常勤':
                 target_indices.append(idx)
        elif group_name == "パート":
            if 'パート' in str(emp_info.get('常勤/パート')):
                 target_indices.append(idx)
        else:
            # 役職名でフィルタリング (これは現状 MIN_ROLE_ON_DUTY などで使われる想定)
            if emp_info.get('役職') == group_name:
                target_indices.append(idx)
    
    # --- DEBUG START: 結果確認 ---
    print(f"DEBUG (get_employees_by_group): Found {len(target_indices)} employees for group '{group_name}'. Indices: {target_indices}")
    # --- DEBUG END ---

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