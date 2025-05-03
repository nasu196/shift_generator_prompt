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

def build_shift_model(employees_df, past_shifts_df, date_range, jp_holidays):
    """OR-Tools CP-SATモデルを構築し、制約を追加する"""
    model = cp_model.CpModel()
    print("Shift model building started...")

    # --- データ準備 ---
    employee_ids = employees_df['職員ID'].tolist()
    num_employees = len(employee_ids)
    num_days = len(date_range)
    all_employees = range(num_employees)
    all_days = range(num_days)

    emp_id_to_info = {emp_id: get_employee_info(employees_df, emp_id) for emp_id in employee_ids}
    emp_idx_to_id = {i: emp_id for i, emp_id in enumerate(employee_ids)}
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
        emp_info = emp_id_to_info.get(emp_idx_to_id.get(e_idx))
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

    # 1. 育休/病休
    for e_idx in all_employees:
        emp_info = emp_id_to_info.get(emp_idx_to_id.get(e_idx))
        if emp_info is not None and emp_info['status'] in ['育休', '病休']:
            status_int = SHIFT_MAP_INT[emp_info['status']]
            for d_idx in all_days:
                model.Add(shifts[(e_idx, d_idx)] == status_int)

    # 2. 希望休
    for e_idx in all_employees:
        emp_info = emp_id_to_info.get(emp_idx_to_id.get(e_idx))
        if emp_info is not None and emp_info['status'] not in ['育休', '病休'] and emp_info['parsed_holidays']:
             for holiday_date in emp_info['parsed_holidays']:
                for d_idx in all_days:
                    if date_range[d_idx] == holiday_date:
                        model.Add(shifts[(e_idx, d_idx)] == SHIFT_MAP_INT['公'])
                        break

    # 3. 直前勤務からの明け/休み
    if past_shifts_lookup is not None:
        for e_idx in all_employees:
            emp_id = emp_idx_to_id.get(e_idx)
            emp_info = emp_id_to_info.get(emp_id)
            if emp_info is None or emp_info['status'] in ['育休', '病休'] or emp_id not in past_shifts_lookup.index:
                continue

            prev_date_str = (START_DATE - timedelta(days=1)).strftime('%#m/%#d')
            prev_2_date_str = (START_DATE - timedelta(days=2)).strftime('%#m/%#d')
            prev_shift = past_shifts_lookup.loc[emp_id, prev_date_str] if prev_date_str in past_shifts_lookup.columns else None
            prev_2_shift = past_shifts_lookup.loc[emp_id, prev_2_date_str] if prev_2_date_str in past_shifts_lookup.columns else None

            if prev_shift == '夜': model.Add(shifts[(e_idx, 0)] == SHIFT_MAP_INT['明'])
            elif prev_shift == '明': model.Add(shifts[(e_idx, 0)] == SHIFT_MAP_INT['公'])
            elif prev_2_shift == '夜' and prev_shift == '明': model.Add(shifts[(e_idx, 0)] == SHIFT_MAP_INT['公'])

    # 追加制約: ステータスが「育休」「病休」でない従業員には 5 を割り当てない
    status_int = SHIFT_MAP_INT['育休'] # 5
    for e_idx in all_employees:
        emp_info = emp_id_to_info.get(emp_idx_to_id.get(e_idx))
        if emp_info is not None and emp_info['status'] not in ['育休', '病休']:
            for d_idx in all_days:
                model.Add(shifts[(e_idx, d_idx)] != status_int)

    # 4. 法定人員配置基準 (応援考慮版)
    personnel_key_map = {"日勤": "日", "早出": "早", "夜勤": "夜"}
    shift_symbols_to_enforce = [personnel_key_map[k] for k in personnel_key_map]

    employees_on_floor = {"1F": [], "2F": []}
    emp_idx_to_floor = {}
    can_help_flags = {}
    for e_idx in all_employees:
        emp_id = emp_idx_to_id[e_idx]
        emp_info = emp_id_to_info.get(emp_id)
        floor = emp_info['担当フロア']
        can_help = emp_info.get('can_help_other_floor', False)
        emp_idx_to_floor[e_idx] = floor
        can_help_flags[e_idx] = can_help
        if floor in employees_on_floor: employees_on_floor[floor].append(e_idx)

    required_personnel_int = {f: {SHIFT_MAP_INT[personnel_key_map[vk]]: c for vk, c in req.items() if personnel_key_map.get(vk) in SHIFT_MAP_INT} for f, req in REQUIRED_PERSONNEL.items() for personnel_key_map in [{'日勤': '日', '早出': '早', '夜勤': '夜'}]}

    for d_idx in all_days:
        for floor_target, required_counts in required_personnel_int.items():
            for shift_int, required_count in required_counts.items():

                # そのフロア担当者のうち、そのシフトについている人のリスト
                assigned_on_floor = []
                for e_idx in employees_on_floor.get(floor_target, []):
                    is_assigned_floor = model.NewBoolVar(f'assigned_{floor_target}_e{e_idx}_d{d_idx}_s{shift_int}')
                    model.Add(shifts[(e_idx, d_idx)] == shift_int).OnlyEnforceIf(is_assigned_floor)
                    model.Add(shifts[(e_idx, d_idx)] != shift_int).OnlyEnforceIf(is_assigned_floor.Not())
                    assigned_on_floor.append(is_assigned_floor)

                # 応援IN/OUTの変数を集める (ifでの評価を避ける)
                help_in_vars = []
                help_out_vars = []
                if floor_target == '1F' and shift_int in helpable_shifts_int:
                    help_in_vars = [
                        var for e in employees_on_floor.get('2F', [])
                        if (var := is_helping_2F_to_1F.get((e, d_idx, shift_int))) is not None
                    ]
                    help_out_vars = [
                        var for e in employees_on_floor.get('1F', [])
                        if (var := is_helping_1F_to_2F.get((e, d_idx, shift_int))) is not None
                    ]
                elif floor_target == '2F' and shift_int in helpable_shifts_int:
                    help_in_vars = [
                        var for e in employees_on_floor.get('1F', [])
                        if (var := is_helping_1F_to_2F.get((e, d_idx, shift_int))) is not None
                    ]
                    help_out_vars = [
                        var for e in employees_on_floor.get('2F', [])
                        if (var := is_helping_2F_to_1F.get((e, d_idx, shift_int))) is not None
                    ]

                # 人員配置制約: (担当者割当数) - (応援OUT) + (応援IN) == 必要数
                model.Add(sum(assigned_on_floor) - sum(help_out_vars) + sum(help_in_vars) == required_count)

    # 応援変数とshifts変数の整合性制約 + 応援不可制約
    all_help_vars = list(is_helping_1F_to_2F.values()) + list(is_helping_2F_to_1F.values())
    for e_idx in all_employees:
        can_help = can_help_flags[e_idx]
        original_floor = emp_idx_to_floor[e_idx]
        for d_idx in all_days:
             for s_int in helpable_shifts_int:
                 # 応援しているなら、必ずそのシフトについていなければならない
                 if original_floor == '1F' and can_help:
                      help_var = is_helping_1F_to_2F.get((e_idx, d_idx, s_int))
                      if help_var is not None:
                           model.Add(shifts[(e_idx, d_idx)] == s_int).OnlyEnforceIf(help_var)
                 elif original_floor == '2F' and can_help:
                      help_var = is_helping_2F_to_1F.get((e_idx, d_idx, s_int))
                      if help_var is not None:
                           model.Add(shifts[(e_idx, d_idx)] == s_int).OnlyEnforceIf(help_var)

                 # 応援できない職員は応援変数 が False でなければならない
                 if not can_help:
                     if original_floor == '1F':
                          help_var = is_helping_1F_to_2F.get((e_idx, d_idx, s_int))
                          if help_var is not None: model.Add(help_var == False)
                     elif original_floor == '2F':
                          help_var = is_helping_2F_to_1F.get((e_idx, d_idx, s_int))
                          if help_var is not None: model.Add(help_var == False)

    # 5. 夜勤ローテーション (夜->明, 明->公)
    for e_idx in all_employees:
        emp_info = emp_id_to_info.get(emp_idx_to_id.get(e_idx))
        if emp_info is not None and emp_info['status'] in ['育休', '病休']: continue
        for d_idx in range(num_days - 1):
            b_night = model.NewBoolVar(f'b_n_e{e_idx}d{d_idx}')
            model.Add(shifts[(e_idx, d_idx)] == SHIFT_MAP_INT['夜']).OnlyEnforceIf(b_night)
            model.Add(shifts[(e_idx, d_idx)] != SHIFT_MAP_INT['夜']).OnlyEnforceIf(b_night.Not())
            model.Add(shifts[(e_idx, d_idx + 1)] == SHIFT_MAP_INT['明']).OnlyEnforceIf(b_night)

            b_ake = model.NewBoolVar(f'b_a_e{e_idx}d{d_idx}')
            model.Add(shifts[(e_idx, d_idx)] == SHIFT_MAP_INT['明']).OnlyEnforceIf(b_ake)
            model.Add(shifts[(e_idx, d_idx)] != SHIFT_MAP_INT['明']).OnlyEnforceIf(b_ake.Not())
            model.Add(shifts[(e_idx, d_idx + 1)] == SHIFT_MAP_INT['公']).OnlyEnforceIf(b_ake)

    # 5b. [ソフト制約] 明けの人数は前日の夜勤の人数とできるだけ一致
    night_shift_int = SHIFT_MAP_INT['夜']
    ake_shift_int = SHIFT_MAP_INT['明']
    ake_count_deviation_penalties = [] # 明け人数逸脱ペナルティ

    for d_idx in all_days:
        # 今日の明けの合計人数 (式として保持)
        ake_today_exprs = []
        for e_idx in all_employees:
            is_ake = model.NewBoolVar(f'is_ake_total_e{e_idx}_d{d_idx}')
            model.Add(shifts[(e_idx, d_idx)] == ake_shift_int).OnlyEnforceIf(is_ake)
            model.Add(shifts[(e_idx, d_idx)] != ake_shift_int).OnlyEnforceIf(is_ake.Not())
            ake_today_exprs.append(is_ake)
        ake_today_sum = cp_model.LinearExpr.Sum(ake_today_exprs)

        # 前日の夜勤の合計人数 (式または定数)
        night_yesterday_sum_expr = None
        if d_idx > 0:
             night_yesterday_vars = []
             for e_idx in all_employees:
                  is_night_yd = model.NewBoolVar(f'is_night_yd_e{e_idx}_d{d_idx-1}')
                  model.Add(shifts[(e_idx, d_idx - 1)] == night_shift_int).OnlyEnforceIf(is_night_yd)
                  model.Add(shifts[(e_idx, d_idx - 1)] != night_shift_int).OnlyEnforceIf(is_night_yd.Not())
                  night_yesterday_vars.append(is_night_yd)
             night_yesterday_sum_expr = cp_model.LinearExpr.Sum(night_yesterday_vars)
        else: # d_idx == 0 (シフト初日)
             count_night_last_day = 0
             if past_shifts_lookup is not None:
                  prev_date_str = (START_DATE - timedelta(days=1)).strftime('%#m/%#d')
                  if prev_date_str in past_shifts_lookup.columns:
                       count_night_last_day = sum(1 for emp_id in past_shifts_lookup.index if past_shifts_lookup.loc[emp_id, prev_date_str] == '夜')
             night_yesterday_sum_expr = count_night_last_day # 定数として扱う

        # 差の絶対値をペナルティとする
        # deviation = |ake_today_sum - night_yesterday_sum_expr|
        max_possible_deviation = num_employees # 差の最大値
        deviation_var = model.NewIntVar(0, max_possible_deviation, f'ake_dev_d{d_idx}')
        # AddAbsEquality を使って deviation_var == abs(差) を定義
        model.AddAbsEquality(deviation_var, ake_today_sum - night_yesterday_sum_expr)
        ake_count_deviation_penalties.append(deviation_var)

    # 6. 連続勤務日数制限
    if past_shifts_lookup is not None:
        for e_idx in all_employees:
            emp_info = emp_id_to_info.get(emp_idx_to_id.get(e_idx))
            if emp_info is None or emp_info['status'] in ['育休', '病休']: continue

            constraints_info = emp_info.get('parsed_constraints', {})
            max_consecutive = constraints_info.get('max_consecutive_work')
            if max_consecutive is None:
                 max_consecutive = MANAGER_MAX_CONSECUTIVE_WORK if emp_info.get('job_title') in MANAGER_ROLES else DEFAULT_MAX_CONSECUTIVE_WORK
            else:
                 max_consecutive = min(max_consecutive, 7) # 安全策

            # 過去の勤務日数を計算
            initial_consecutive_work = 0
            emp_id = emp_idx_to_id.get(e_idx)
            if emp_id in past_shifts_lookup.index:
                for i in range(1, max_consecutive + 1):
                    past_date_str = (START_DATE - timedelta(days=i)).strftime('%#m/%#d')
                    if past_date_str in past_shifts_lookup.columns:
                        past_shift = past_shifts_lookup.loc[emp_id, past_date_str]
                        if past_shift and past_shift not in ['公', '育休', '病休']:
                            initial_consecutive_work += 1
                        else: break
                    else: break

            # 制約を追加
            for d_start in range(-initial_consecutive_work, num_days - max_consecutive):
                vars_in_window = []
                for d_offset in range(max_consecutive + 1):
                    d_current = d_start + d_offset
                    if d_current < 0: continue # 過去分は initial_consecutive_work で考慮済
                    if d_current >= num_days: break
                    # 勤務シフトかどうかを示すブール変数 (True=勤務, False=休み)
                    is_working_var = model.NewBoolVar(f'is_work_e{e_idx}_d{d_current}')
                    allowed_tuples = [(s,) for s in WORKING_SHIFTS_INT]
                    model.AddAllowedAssignments((shifts[(e_idx, d_current)],), allowed_tuples).OnlyEnforceIf(is_working_var)
                    model.AddForbiddenAssignments((shifts[(e_idx, d_current)],), allowed_tuples).OnlyEnforceIf(is_working_var.Not())
                    vars_in_window.append(is_working_var)

                if d_start < 0:
                    # 期間開始時のウィンドウ (過去の連勤数を考慮)
                     effective_window_size = max_consecutive + 1 + d_start
                     if effective_window_size > 0:
                          model.Add(sum(vars_in_window) <= effective_window_size - 1)
                elif vars_in_window:
                     # 通常のウィンドウ
                     model.Add(sum(vars_in_window) <= max_consecutive)

    # 7. 個別の制約 (一部)
    night_preference_penalties = [] # 夜勤希望ペナルティ
    for e_idx in all_employees:
        emp_info = emp_id_to_info.get(emp_idx_to_id.get(e_idx))
        if emp_info is None or emp_info['status'] in ['育休', '病休']:
            continue
        constraints_info = emp_info.get('parsed_constraints', {})

        # 禁止シフト (ハード制約のまま)
        disallowed_shifts = constraints_info.get('disallowed_shifts', [])
        if disallowed_shifts:
            disallowed_ints = [SHIFT_MAP_INT[s] for s in disallowed_shifts if s in SHIFT_MAP_INT]
            if disallowed_ints:
                for d_idx in all_days:
                    # Add() がリストを取らないのでループが必要
                    for dis_int in disallowed_ints:
                        model.Add(shifts[(e_idx, d_idx)] != dis_int)

        # 特定日付の希望シフト
        preferred_shifts = constraints_info.get('preferred_date_shift', {})
        if preferred_shifts:
            for pref_date, pref_shift_sym in preferred_shifts.items():
                 if pref_shift_sym in SHIFT_MAP_INT:
                      pref_shift_int = SHIFT_MAP_INT[pref_shift_sym]
                      for d_idx in all_days:
                           if date_range[d_idx] == pref_date:
                                if pref_shift_int == SHIFT_MAP_INT['夜']:
                                    # 夜勤希望はソフト制約に
                                    penalty_var = model.NewBoolVar(f'night_pref_penalty_e{e_idx}_d{d_idx}')
                                    night_preference_penalties.append(penalty_var)
                                    # 夜勤でない場合にペナルティ
                                    model.Add(shifts[(e_idx, d_idx)] != pref_shift_int).OnlyEnforceIf(penalty_var)
                                    model.Add(shifts[(e_idx, d_idx)] == pref_shift_int).OnlyEnforceIf(penalty_var.Not())
                                else:
                                    # 夜勤以外の希望はハード制約のまま
                                    model.Add(shifts[(e_idx, d_idx)] == pref_shift_int)
                                break # 日付が見つかったら内側ループを抜ける

    # 8. [必須] 休日数
    total_days_in_period = num_days
    required_off_days_full_time = 8 # 正職員の必須公休数

    for e_idx in all_employees:
        emp_info = emp_id_to_info.get(emp_idx_to_id.get(e_idx))
        if emp_info is None or emp_info['status'] in ['育休', '病休']:
            continue

        constraints_info = emp_info.get('parsed_constraints', {})
        job_type = emp_info.get('常勤/パート', '') # 正職員かパートか判定用

        required_off_days = None
        # 正職員の場合 (文字列 '常勤' を含むかで判定)
        if '常勤' in job_type and 'パート' not in job_type:
            required_off_days = required_off_days_full_time
        # パート職員の場合 (月間勤務日数が指定されているか)
        elif 'パート' in job_type and 'monthly_work_days' in constraints_info:
            monthly_work_days = constraints_info['monthly_work_days']
            # 期間中の総日数から勤務日数を引いて最低休日数を計算
            # 注意: 期間が月をまたぐ場合、厳密な計算は難しい。ここでは単純に期間日数から計算。
            required_off_days = max(0, total_days_in_period - monthly_work_days)
            # print(f"Debug: パート {emp_idx_to_id.get(e_idx)}, 月間{monthly_work_days}日 -> 最低公休 {required_off_days}")

        if required_off_days is not None:
            # 公休(ID 0) の数をカウント
            # 修正: ブール変数 is_off を作成し、その合計で制約する
            is_off_vars = []
            for d_idx in all_days:
                is_off = model.NewBoolVar(f'is_off_e{e_idx}_d{d_idx}')
                model.Add(shifts[(e_idx, d_idx)] == SHIFT_MAP_INT['公']).OnlyEnforceIf(is_off)
                model.Add(shifts[(e_idx, d_idx)] != SHIFT_MAP_INT['公']).OnlyEnforceIf(is_off.Not())
                is_off_vars.append(is_off)
            model.Add(sum(is_off_vars) >= required_off_days)

    # 9. [必須] 個別条件 - 組み合わせNG (avoid_night_shift_with)
    # 職員ID -> 職員インデックス のマッピングを作成
    emp_id_to_idx = {emp_id: idx for idx, emp_id in emp_idx_to_id.items()}

    for e_idx in all_employees:
        emp_info = emp_id_to_info.get(emp_idx_to_id.get(e_idx))
        if emp_info is None or emp_info['status'] in ['育休', '病休']:
            continue
        constraints_info = emp_info.get('parsed_constraints', {})
        avoid_ids = constraints_info.get('avoid_night_shift_with', [])

        if avoid_ids:
            for avoid_id in avoid_ids:
                if avoid_id in emp_id_to_idx:
                    avoid_e_idx = emp_id_to_idx[avoid_id]
                    # 同じ日に両者が夜勤(ID 3)になることを禁止
                    for d_idx in all_days:
                        # (e_idxが夜勤 b1) and (avoid_e_idxが夜勤 b2) は不可
                        # not (b1 and b2) <=> not(b1) or not(b2)
                        b1 = model.NewBoolVar(f'avd_n_e{e_idx}_d{d_idx}')
                        b2 = model.NewBoolVar(f'avd_n_e{avoid_e_idx}_d{d_idx}')
                        model.Add(shifts[(e_idx, d_idx)] == SHIFT_MAP_INT['夜']).OnlyEnforceIf(b1)
                        model.Add(shifts[(e_idx, d_idx)] != SHIFT_MAP_INT['夜']).OnlyEnforceIf(b1.Not())
                        model.Add(shifts[(avoid_e_idx, d_idx)] == SHIFT_MAP_INT['夜']).OnlyEnforceIf(b2)
                        model.Add(shifts[(avoid_e_idx, d_idx)] != SHIFT_MAP_INT['夜']).OnlyEnforceIf(b2.Not())
                        # b1 と b2 が同時にTrueになることを禁止 (どちらか一方はFalse)
                        model.AddBoolOr([b1.Not(), b2.Not()])
                else:
                     print(f"警告: 組み合わせNGの相手 {avoid_id} が従業員リストにいません。")

    # 10. [必須] 個別条件 - 勤務種別制限 (allowed_shifts)
    for e_idx in all_employees:
        emp_info = emp_id_to_info.get(emp_idx_to_id.get(e_idx))
        if emp_info is None or emp_info['status'] in ['育休', '病休']:
            continue
        constraints_info = emp_info.get('parsed_constraints', {})
        allowed_shifts_sym = constraints_info.get('allowed_shifts') # 例: ['日', '早']

        if allowed_shifts_sym:
            allowed_ints = [SHIFT_MAP_INT[s] for s in allowed_shifts_sym if s in SHIFT_MAP_INT]
            # 許可リストに含まれない全シフト(通常勤務+公休)を禁止する
            all_normal_shift_ints = list(SHIFT_MAP_INT.values()) # 0..5
            # 育休/病休は除く (これらは status で固定されているはず)
            forbidden_ints = [s_int for s_int in all_normal_shift_ints if s_int not in allowed_ints and s_int != SHIFT_MAP_INT['育休']]
            if forbidden_ints:
                 for d_idx in all_days:
                      model.AddForbiddenAssignments([shifts[(e_idx, d_idx)]], [(f_int,) for f_int in forbidden_ints])

    # 11. [ソフト制約] 個別条件 - 曜日希望 (preferred_weekday_shift)
    weekday_penalties = [] # 曜日希望ペナルティ変数を格納 (再有効化)
    for e_idx in all_employees:
        emp_info = emp_id_to_info.get(emp_idx_to_id.get(e_idx))
        if emp_info is None or emp_info['status'] in ['育休', '病休']:
            continue
        constraints_info = emp_info.get('parsed_constraints', {})
        preferred_weekday_shifts = constraints_info.get('preferred_weekday_shift')

        if preferred_weekday_shifts:
            for d_idx in all_days:
                target_date = date_range[d_idx]
                weekday = target_date.weekday()
                if weekday in preferred_weekday_shifts:
                    pref_shift_sym = preferred_weekday_shifts[weekday]
                    if pref_shift_sym in SHIFT_MAP_INT:
                        pref_shift_int = SHIFT_MAP_INT[pref_shift_sym]
                        # ソフト制約に戻す: ペナルティ変数を導入
                        penalty_var = model.NewBoolVar(f'weekday_penalty_e{e_idx}_d{d_idx}')
                        weekday_penalties.append(penalty_var)
                        # 希望シフトでない場合にペナルティ (penalty_var = 1)
                        model.Add(shifts[(e_idx, d_idx)] != pref_shift_int).OnlyEnforceIf(penalty_var)
                        model.Add(shifts[(e_idx, d_idx)] == pref_shift_int).OnlyEnforceIf(penalty_var.Not())

    # 12. [ソフト制約] Aさん, Bさんのカレンダー勤務 (目的関数で最小化)
    calendar_employees = ['A', 'B']
    default_work_shift = SHIFT_MAP_INT['日']
    weekend_off_shift = SHIFT_MAP_INT['公']
    ab_schedule_penalties = [] # ペナルティ変数を格納するリスト

    for e_idx in all_employees:
        emp_id = emp_idx_to_id.get(e_idx)
        if emp_id in calendar_employees:
            emp_info = emp_id_to_info.get(emp_id)
            if emp_info is None or emp_info['status'] in ['育休', '病休']:
                 continue
            requested_holidays = emp_info.get('parsed_holidays', [])

            for d_idx in all_days:
                target_date = date_range[d_idx]
                weekday = target_date.weekday()

                # 希望休でない日のみペナルティを考慮
                if target_date not in requested_holidays:
                    penalty_var = model.NewBoolVar(f'ab_penalty_e{e_idx}_d{d_idx}')
                    ab_schedule_penalties.append(penalty_var)

                    if weekday >= 5: # 土日 -> 公休が望ましい
                        # 公休でない場合にペナルティ (penalty_var = 1)
                        model.Add(shifts[(e_idx, d_idx)] != weekend_off_shift).OnlyEnforceIf(penalty_var)
                        model.Add(shifts[(e_idx, d_idx)] == weekend_off_shift).OnlyEnforceIf(penalty_var.Not())
                    else: # 平日 -> 日勤が望ましい
                        # 日勤でない場合にペナルティ (penalty_var = 1)
                        model.Add(shifts[(e_idx, d_idx)] != default_work_shift).OnlyEnforceIf(penalty_var)
                        model.Add(shifts[(e_idx, d_idx)] == default_work_shift).OnlyEnforceIf(penalty_var.Not())

    # 13. [必須] パート職員の最大勤務日数
    for e_idx in all_employees:
        emp_info = emp_id_to_info.get(emp_idx_to_id.get(e_idx))
        if emp_info is None or emp_info['status'] in ['育休', '病休']:
            continue

        constraints_info = emp_info.get('parsed_constraints', {})
        job_type = emp_info.get('常勤/パート', '')

        # パート職員で月間勤務日数の指定がある場合
        if 'パート' in job_type and 'monthly_work_days' in constraints_info:
            max_work_days = constraints_info['monthly_work_days']

            # 期間中の勤務日数 (WORKING_SHIFTS_INT に含まれるシフト) をカウント
            is_working_vars_for_emp = []
            allowed_tuples = [(s,) for s in WORKING_SHIFTS_INT]
            for d_idx in all_days:
                # 勤務日かどうかを示すブール変数 (連勤計算とは別名にする)
                temp_is_working_var = model.NewBoolVar(f'is_work_max_e{e_idx}_d{d_idx}')
                model.AddAllowedAssignments((shifts[(e_idx, d_idx)],), allowed_tuples).OnlyEnforceIf(temp_is_working_var)
                model.AddForbiddenAssignments((shifts[(e_idx, d_idx)],), allowed_tuples).OnlyEnforceIf(temp_is_working_var.Not())
                is_working_vars_for_emp.append(temp_is_working_var)

            # 勤務日数の合計が指定された最大日数以下であること
            model.Add(sum(is_working_vars_for_emp) <= max_work_days)

    # 14. [必須] 土日祝は副主任が最低1名勤務
    vice_manager_indices = [
        e_idx for e_idx in all_employees
        if (emp_info := emp_id_to_info.get(emp_idx_to_id.get(e_idx))) is not None
        and emp_info.get('job_title') == '副主任'
        and emp_info.get('status') not in ['育休', '病休'] # 稼働可能な副主任のみ
    ]

    if vice_manager_indices:
        for d_idx in all_days:
            target_date = date_range[d_idx]
            weekday = target_date.weekday()
            is_weekend_or_holiday = (weekday >= 5) or (target_date in jp_holidays)

            if is_weekend_or_holiday:
                # その日に副主任が休み(公休 or 育休/病休)かどうかを示す変数リスト
                is_off_vm_vars = []
                off_shift_ints_vm = OFF_SHIFT_INTS # [0, 5]
                allowed_off_tuples = [(s,) for s in off_shift_ints_vm]

                for vm_idx in vice_manager_indices:
                    is_off = model.NewBoolVar(f'is_off_vm_e{vm_idx}_d{d_idx}')
                    # is_off が True <=> shifts[vm_idx, d_idx] が休み系シフト
                    model.AddAllowedAssignments((shifts[(vm_idx, d_idx)],), allowed_off_tuples).OnlyEnforceIf(is_off)
                    model.AddForbiddenAssignments((shifts[(vm_idx, d_idx)],), allowed_off_tuples).OnlyEnforceIf(is_off.Not())
                    is_off_vm_vars.append(is_off)

                # 副主任の休み合計人数が (副主任総数 - 1) 以下であることを制約
                # = 最低1人は休みではない (勤務している)
                model.Add(sum(is_off_vm_vars) <= len(vice_manager_indices) - 1)

    # 15. [ハード制約] 土日祝休み希望 (prefer_weekends_off)
    for e_idx in all_employees:
        emp_info = emp_id_to_info.get(emp_idx_to_id.get(e_idx))
        if emp_info is None or emp_info['status'] in ['育休', '病休']:
            continue
        constraints_info = emp_info.get('parsed_constraints', {})
        if constraints_info.get('prefer_weekends_off', False):
            forbidden_shifts_int = WORKING_SHIFTS_INT
            for d_idx in all_days:
                target_date = date_range[d_idx]
                weekday = target_date.weekday()
                is_weekend_or_holiday = (weekday >= 5) or (target_date in jp_holidays)
                if is_weekend_or_holiday:
                    for forbidden_int in forbidden_shifts_int:
                        # デバッグプリントを削除
                        model.Add(shifts[(e_idx, d_idx)] != forbidden_int)

    # 16. [追加] 常勤職員は4連休以上禁止
    max_consecutive_off = 3 # 最大3連休まで許容
    off_day_int = SHIFT_MAP_INT['公'] # 公休のID

    for e_idx in all_employees:
        emp_info = emp_id_to_info.get(emp_idx_to_id.get(e_idx))
        if emp_info is None or emp_info['status'] in ['育休', '病休']:
            continue

        job_type = emp_info.get('常勤/パート', '')
        # パート職員は対象外とする
        if 'パート' in job_type:
             continue

        # is_off_day[d] = True <=> shifts[e,d] == 公休
        is_off_day_vars = [model.NewBoolVar(f'is_off_day_e{e_idx}_d{d_idx}') for d_idx in all_days]
        for d_idx in all_days:
             model.Add(shifts[(e_idx, d_idx)] == off_day_int).OnlyEnforceIf(is_off_day_vars[d_idx])
             model.Add(shifts[(e_idx, d_idx)] != off_day_int).OnlyEnforceIf(is_off_day_vars[d_idx].Not())

        # 4日間のウィンドウで公休が4つになることを禁止
        window_size = max_consecutive_off + 1 # 4
        for start_idx in range(num_days - window_size + 1):
             model.Add(sum(is_off_day_vars[d] for d in range(start_idx, start_idx + window_size)) <= max_consecutive_off)

    # 17. [ソフト制約] 特定パート職員の合計公休日数指定
    specific_total_offs = {
        'Q': 14,
        'AM': 15,
        'AN': 14,
        'AO': 13,
        'AL': 11, # ALさんを追加
    }
    off_day_int_total = SHIFT_MAP_INT['公']
    total_off_day_deviation_penalties = [] # 合計公休数逸脱ペナルティ

    for emp_id, target_off_count in specific_total_offs.items():
        if emp_id in emp_id_to_idx:
            e_idx = emp_id_to_idx[emp_id]
            emp_info = emp_id_to_info.get(emp_id)
            if emp_info is not None and emp_info['status'] in ['育休', '病休']:
                continue

            is_off_vars_total = []
            for d_idx in all_days:
                is_off_total = model.NewBoolVar(f'is_off_total_e{e_idx}_d{d_idx}')
                model.Add(shifts[(e_idx, d_idx)] == off_day_int_total).OnlyEnforceIf(is_off_total)
                model.Add(shifts[(e_idx, d_idx)] != off_day_int_total).OnlyEnforceIf(is_off_total.Not())
                is_off_vars_total.append(is_off_total)

            # 実際の公休数
            actual_off_count_expr = sum(is_off_vars_total)

            # 目標との差の絶対値をペナルティとする
            max_possible_deviation = num_days # 差の最大値
            deviation_var = model.NewIntVar(0, max_possible_deviation, f'total_off_dev_e{e_idx}')
            model.AddAbsEquality(deviation_var, actual_off_count_expr - target_off_count)
            total_off_day_deviation_penalties.append(deviation_var)

            # 以前のハード制約は削除
            # print(f"DEBUG: Adding total off days constraint for {emp_id}: exactly {target_off_count} days")
            # model.Add(sum(is_off_vars_total) == target_off_count)
        else:
             print(f"警告: 合計休日数指定の従業員ID {emp_id} が見つかりません。")

    # --- 目的関数 --- (ペナルティ合計 + 応援回数 + 明け人数逸脱 + 夜勤希望逸脱 + 合計休日逸脱 + 公休均等化 を最小化)
    # 各ペナルティの重みを定義 (調整可能)
    ab_penalty_weight = 0.2 # A/Bカレンダー逸脱の重みを 0.2 に設定
    weekday_penalty_weight = 1
    night_pref_penalty_weight = 1
    help_penalty_weight = 1
    ake_deviation_penalty_weight = 1
    total_off_day_penalty_weight = 1
    off_balance_penalty_weight = 1

    # 各ペナルティ/コスト項の合計を計算
    all_penalties_base = weekday_penalties + night_preference_penalties # 重み1以外のペナルティ
    all_help_vars = list(is_helping_1F_to_2F.values()) + list(is_helping_2F_to_1F.values())
    total_help_count = sum(all_help_vars)
    total_ake_deviation = sum(ake_count_deviation_penalties)
    total_off_day_deviation = sum(total_off_day_deviation_penalties)
    # 公休数均等化 (off_days_difference は定義済み)

    # 修正: OR-Tools の式として目的関数を構築
    objective_terms = []
    if ab_schedule_penalties:
        # LinearExpr.Sum はブール変数のリストを受け取れる
        objective_terms.append(ab_penalty_weight * cp_model.LinearExpr.Sum(ab_schedule_penalties))
    if weekday_penalties:
        objective_terms.append(weekday_penalty_weight * cp_model.LinearExpr.Sum(weekday_penalties))
    if night_preference_penalties:
        objective_terms.append(night_pref_penalty_weight * cp_model.LinearExpr.Sum(night_preference_penalties))
    if all_help_vars: # all_help_vars は既にブール変数のリスト
        objective_terms.append(help_penalty_weight * cp_model.LinearExpr.Sum(all_help_vars))
    if ake_count_deviation_penalties: # これはIntVarのリストなので、そのまま合計できるはず
        objective_terms.append(ake_deviation_penalty_weight * cp_model.LinearExpr.Sum(ake_count_deviation_penalties))
    if total_off_day_deviation_penalties: # これもIntVarのリスト
         objective_terms.append(total_off_day_penalty_weight * cp_model.LinearExpr.Sum(total_off_day_deviation_penalties))
    if 'off_days_difference' in locals() and len(full_time_employee_indices) > 1:
         # off_days_difference はIntVarなのでそのまま使える
         objective_terms.append(off_balance_penalty_weight * off_days_difference)

    if objective_terms:
        model.Minimize(cp_model.LinearExpr.Sum(objective_terms))
        print("Objective function set: Minimize Weighted Penalties (OR-Tools Expr).")

    print("Constraints added.")
    return model, shifts, employee_ids, date_range # モデルと変数を返す 