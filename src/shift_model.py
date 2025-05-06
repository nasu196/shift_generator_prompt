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
        employee_id = rule.get('employee') # Primary employee ID
        employee1_id = rule.get('employee1') # Secondary for rules like FORBID_SIMULTANEOUS_SHIFT

        primary_e_idx = emp_id_to_idx.get(employee_id)
        employee1_idx = emp_id_to_idx.get(employee1_id)

        assign_to_idx = None
        if primary_e_idx is not None:
            # 'employee' が存在し、有効な場合
            assign_to_idx = primary_e_idx
        elif employee1_idx is not None:
            # 'employee' がなく 'employee1' が存在する場合
            # (組み合わせNGルールなどは employee1 に紐づけて処理する)
            assign_to_idx = employee1_idx
        # 他にも employee キーを持たないルールタイプがあれば、ここでハンドリングを追加

        if assign_to_idx is not None:
             employee_specific_rules[assign_to_idx].append(rule)
        else:
            # どちらのIDも見つからないか、関連付けられないルール
            invalid_id_info = f"employee='{employee_id}' or employee1='{employee1_id}'"
            print(f"警告: ルール内の従業員ID ({invalid_id_info}) が見つからないか、ルールを関連付けられません。ルールをスキップ: {rule}")
            continue

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

            # 'ASSIGN' から 'SPECIFY_DATE_SHIFT' に変更
            if rule_type == 'SPECIFY_DATE_SHIFT':
                target_date = rule.get('date')
                shift_sym = rule.get('shift')
                is_hard = rule.get('is_hard') # is_hard を取得 (デフォルトTrueはやめる)

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
                      else:
                         print(f"警告(モデル): TOTAL_SHIFT_COUNT の shifts が無効: {rule}")
                 else:
                     print(f"警告(モデル): 無効または重複する TOTAL_SHIFT_COUNT ルール: {rule}")

            elif rule_type == 'MAX_CONSECUTIVE_OFF':
                max_off_days = rule.get('max_days')
                if isinstance(max_off_days, int) and max_off_days >= 0 and f'max_off_{e_idx}' not in processed_rule_types:
                    # (MAX_CONSECUTIVE_WORK に似たロジックで連続公休を制限)
                    # 公休を判定する変数を作成
                    is_off = [model.NewBoolVar(f'is_off_r_maxoff_e{e_idx}_d{d_idx}') for d_idx in all_days]
                    off_tuples = [(off_int,) for off_int in OFF_SHIFT_INTS] # 公休または特殊休
                    for d_idx in all_days:
                        model.AddAllowedAssignments((shifts[(e_idx, d_idx)],), off_tuples).OnlyEnforceIf(is_off[d_idx])
                        model.AddForbiddenAssignments((shifts[(e_idx, d_idx)],), off_tuples).OnlyEnforceIf(is_off[d_idx].Not())

                    # 過去の連続公休日数を計算 (過去シフトが必要)
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

                    # ウィンドウ制約を追加
                    window_size = max_off_days + 1
                    for d_start in range(-initial_consecutive_off, num_days - max_off_days):
                        vars_in_window = []
                        for d_offset in range(window_size):
                            d_current = d_start + d_offset
                            if d_current < 0: continue
                            if d_current >= num_days: break
                            vars_in_window.append(is_off[d_current])

                        if d_start < 0:
                            effective_window_size = window_size + d_start
                            if effective_window_size > 0: model.Add(sum(vars_in_window) <= effective_window_size - 1)
                        elif vars_in_window: model.Add(sum(vars_in_window) <= max_off_days)

                    processed_rule_types.add(f'max_off_{e_idx}') # 処理済みマーク
                else:
                    print(f"警告(モデル): 無効または重複する MAX_CONSECUTIVE_OFF ルール: {rule}")

            elif rule_type == 'FORBID_SHIFT_SEQUENCE':
                pre_shift_sym = rule.get('preceding_shift')
                sub_shift_sym = rule.get('subsequent_shift')
                rule_key = f"forbid_seq_{e_idx}_{pre_shift_sym}_{sub_shift_sym}"
                if pre_shift_sym in SHIFT_MAP_INT and sub_shift_sym in SHIFT_MAP_INT and rule_key not in processed_rule_types:
                    pre_shift_int = SHIFT_MAP_INT[pre_shift_sym]
                    sub_shift_int = SHIFT_MAP_INT[sub_shift_sym]
                    for d_idx in range(num_days - 1): # 最終日は翌日がないので除外
                        # d日目が先行シフト かつ d+1日目が後続シフト、という組み合わせを禁止
                        b1 = model.NewBoolVar(f'is_pre_fseq_e{e_idx}_d{d_idx}')
                        b2 = model.NewBoolVar(f'is_sub_fseq_e{e_idx}_d{d_idx+1}')
                        model.Add(shifts[(e_idx, d_idx)] == pre_shift_int).OnlyEnforceIf(b1)
                        model.Add(shifts[(e_idx, d_idx)] != pre_shift_int).OnlyEnforceIf(b1.Not())
                        model.Add(shifts[(e_idx, d_idx + 1)] == sub_shift_int).OnlyEnforceIf(b2)
                        model.Add(shifts[(e_idx, d_idx + 1)] != sub_shift_int).OnlyEnforceIf(b2.Not())
                        # b1 と b2 が両方 True になることを禁止 (Or を使う)
                        model.AddBoolOr([b1.Not(), b2.Not()])
                    processed_rule_types.add(rule_key)
                else:
                     print(f"警告(モデル): 無効または重複する FORBID_SHIFT_SEQUENCE ルール: {rule}")

            # PREFER_SHIFT_SEQUENCE のロジックを削除し、ENFORCE_SHIFT_SEQUENCE のハード制約を実装
            elif rule_type == 'ENFORCE_SHIFT_SEQUENCE':
                pre_shift_sym = rule.get('preceding_shift')
                sub_shift_sym = rule.get('subsequent_shift')
                rule_key = f"enforce_seq_{e_idx}_{pre_shift_sym}_{sub_shift_sym}"
                if pre_shift_sym in SHIFT_MAP_INT and sub_shift_sym in SHIFT_MAP_INT and rule_key not in processed_rule_types:
                    pre_shift_int = SHIFT_MAP_INT[pre_shift_sym]
                    sub_shift_int = SHIFT_MAP_INT[sub_shift_sym]
                    for d_idx in range(num_days - 1):
                        # d日目が先行シフトならば、d+1日目は後続シフトでなければならない
                        b_pre = model.NewBoolVar(f'is_pre_eseq_e{e_idx}_d{d_idx}')
                        model.Add(shifts[(e_idx, d_idx)] == pre_shift_int).OnlyEnforceIf(b_pre)
                        model.Add(shifts[(e_idx, d_idx)] != pre_shift_int).OnlyEnforceIf(b_pre.Not())
                        # b_pre が True ならば、shifts[(e_idx, d_idx + 1)] == sub_shift_int が強制される
                        model.Add(shifts[(e_idx, d_idx + 1)] == sub_shift_int).OnlyEnforceIf(b_pre)
                    processed_rule_types.add(rule_key)
                else:
                    print(f"警告(モデル): 無効または重複する ENFORCE_SHIFT_SEQUENCE ルール: {rule}")

            # --- ソフト制約の処理 (structured_rules ベースに修正) ---
            elif rule_type == 'PREFER_WEEKDAY_SHIFT':
                 weekday = rule.get('weekday')
                 shift_sym = rule.get('shift')
                 weight = rule.get('weight', 1) # デフォルトウェイト追加
                 if weekday is not None and shift_sym in SHIFT_MAP_INT:
                      shift_int = SHIFT_MAP_INT[shift_sym]
                      for d_idx in all_days:
                           if date_range[d_idx].weekday() == weekday:
                                penalty_var = model.NewBoolVar(f'weekday_penalty_e{e_idx}_d{d_idx}')
                                # 重みを考慮してペナルティリストに追加 (重み * 変数)
                                # LinearExpr に整数係数が必要なため、weightを整数化(丸め)して使う。より厳密には浮動小数点係数を扱える方法を検討。
                                weekday_penalties.append(penalty_var * int(round(weight * 100))) # 例: 100倍して整数化
                                model.Add(shifts[(e_idx, d_idx)] != shift_int).OnlyEnforceIf(penalty_var)
                                model.Add(shifts[(e_idx, d_idx)] == shift_int).OnlyEnforceIf(penalty_var.Not())
                 else:
                     print(f"警告(モデル): 無効な PREFER_WEEKDAY_SHIFT ルール: {rule}")

            elif rule_type == 'UNKNOWN_FORMAT' or rule_type == 'PARSE_ERROR' or rule_type == 'UNPARSABLE':
                 print(f"情報(モデル): 処理できないルール: {rule}")
            # else: print(f"情報(モデル): 未対応のルールタイプ: {rule_type}") # Unknownはパーサーで弾かれるはず

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
    # 明け人数≒前日夜勤人数のペナルティ計算ロジックは変更なし
    # ...

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

    # ソフト制約 5: 公休均等化 (コメントアウト中)
    # ...

    # ソフト制約 6: 特定日付の夜勤希望 (SPECIFY_DATE_SHIFT の is_hard=False で処理される)
    # (night_preference_penalties は SPECIFY_DATE_SHIFT の処理ループで作成済み)

    # --- 目的関数 --- (公休均等化ペナルティを除外)
    objective_terms = []
    # 各ペナルティリスト名と重み (weight はここで掛ける)
    penalties_with_weights = [
        (ab_schedule_penalties, 1), # 重みは変数作成時に適用済み
        (weekday_penalties, 1),     # 重みは変数作成時に適用済み
        (night_preference_penalties, 1), # 重みは変数作成時に適用済み
        # (all_help_vars, 1), # 応援スコープ外
        (ake_count_deviation_penalties, 1),
        # (total_off_day_deviation_penalties, 1) # ハードコード削除により不要
    ]

    # 目的関数にペナルティ項を追加
    for penalty_list, weight in penalties_with_weights:
         if penalty_list:
             # リスト内の各要素(IntVar * weight_int)の合計を取る
             objective_terms.append(cp_model.LinearExpr.Sum(penalty_list))

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