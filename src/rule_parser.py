# 整形済み定型文ルールパーサー
import json # JSON形式を扱う場合 (今回はPython辞書を直接扱う)
from datetime import date, timedelta
import re # 年なし日付パース用

# SHIFT_MAP_INT は日付以外のパラメータ検証で使えるかもしれない
from src.constants import SHIFT_MAP_INT

# 有効なシフト記号のセット (検証用)
VALID_SHIFT_SYMBOLS = set(SHIFT_MAP_INT.keys())

# 年なし日付をパースするための正規表現 (MM-DD, M-D, MM/DD, M/D 形式を想定)
DATE_WITHOUT_YEAR_REGEX = re.compile(r"^(\d{1,2})[/-](\d{1,2})$")

def parse_and_validate_date(date_str, start_date, end_date):
    """
    AIが出力した日付文字列を検証し、期間内のdateオブジェクトに変換する。
    年が省略されている場合は、start_date/end_dateの年を補完して試す。
    無効または期間外の場合は None を返す。
    """
    if not isinstance(date_str, str):
        return None, "Date must be a string."

    try:
        # まず YYYY-MM-DD 形式で試す
        parsed_date = date.fromisoformat(date_str)
        if start_date <= parsed_date <= end_date:
            return parsed_date, None # 期間内ならOK
        else:
            return None, f"Date {parsed_date} is outside the period [{start_date}, {end_date}]."
    except ValueError:
        # YYYY-MM-DD で失敗した場合、年なし形式 (MM-DD, M/Dなど) を試す
        match = DATE_WITHOUT_YEAR_REGEX.match(date_str)
        if match:
            try:
                month = int(match.group(1))
                day = int(match.group(2))

                # start_dateの年で試す
                date_with_start_year = date(start_date.year, month, day)
                if start_date <= date_with_start_year <= end_date:
                    return date_with_start_year, None

                # start_dateの年でダメで、年末年始跨ぎの場合、end_dateの年で試す
                if start_date.year < end_date.year:
                    date_with_end_year = date(end_date.year, month, day)
                    if start_date <= date_with_end_year <= end_date:
                        return date_with_end_year, None

                # どちらの年も期間外
                return None, f"Date {month}/{day} (assuming year {start_date.year} or {end_date.year}) is outside the period [{start_date}, {end_date}]."
            except ValueError as e_date: # 無効な月日 (例: 2/30) や年の組み合わせ (例: 2/29でうるう年でない)
                return None, f"Invalid date value: {date_str} ({e_date})"
        else:
            # どちらの形式でもパースできない
            return None, f"Unrecognized date format: {date_str}"

def validate_and_transform_rule(rule_data, start_date, end_date):
    """
    単一の構造化ルールデータ(辞書)を検証し、必要なら変換する。
    start_date, end_date を使って日付の年を補完・検証する。
    無効な場合は rule_type を 'INVALID' にして返す。
    """
    if not isinstance(rule_data, dict):
        return {'rule_type': 'INVALID', 'reason': 'Data is not a dictionary.'}

    rule_type = rule_data.get('rule_type')
    # UNPARSABLE はそのまま返す
    if rule_type == 'UNPARSABLE':
        return rule_data

    # employee または employee1 が必須で、文字列であること
    employee = rule_data.get('employee') or rule_data.get('employee1')
    if not employee or not isinstance(employee, str):
        return {'rule_type': 'INVALID', 'reason': 'Missing or invalid employee/employee1.'}

    if not rule_type:
        return {'rule_type': 'INVALID', 'reason': 'Missing rule_type.'}

    # is_hard があればブール型かチェック
    if 'is_hard' in rule_data and not isinstance(rule_data['is_hard'], bool):
         return {'rule_type': 'INVALID', 'reason': 'is_hard must be a boolean.'}

    # employee2 があれば文字列かチェック
    if 'employee2' in rule_data and not isinstance(rule_data['employee2'], str):
         return {'rule_type': 'INVALID', 'reason': 'employee2 must be a string.'}

    # --- 日付関連の処理 --- 
    if 'date' in rule_data:
        valid_date, reason = parse_and_validate_date(rule_data['date'], start_date, end_date)
        if valid_date:
            rule_data['date'] = valid_date # dateオブジェクトに置き換え
        else:
            return {'rule_type': 'INVALID', 'reason': reason or "Invalid date found."} # 理由があれば使う

    # シフト記号の検証関数
    def is_valid_shift(shift):
        return isinstance(shift, str) and shift in VALID_SHIFT_SYMBOLS

    # --- ルールタイプごとの検証 --- 
    if rule_type == 'SPECIFY_DATE_SHIFT':
        # date は上で検証・変換済み
        if 'date' not in rule_data or not isinstance(rule_data.get('date'), date):
            # 通常ここには来ないはずだが念のため
             return {'rule_type': 'INVALID', 'reason': f"Missing or invalid date after validation for {rule_type}"}
        shift = rule_data.get('shift')
        if not is_valid_shift(shift):
            return {'rule_type': 'INVALID', 'reason': f"Invalid or missing shift symbol for {rule_type}: {shift}"}
        if not isinstance(rule_data.get('is_hard'), bool):
             return {'rule_type': 'INVALID', 'reason': f"Missing or invalid is_hard for {rule_type}"}

    elif rule_type == 'MAX_CONSECUTIVE_WORK':
        if not isinstance(rule_data.get('max_days'), int) or rule_data['max_days'] <= 0:
             return {'rule_type': 'INVALID', 'reason': f"Invalid max_days for {rule_type}: {rule_data.get('max_days')}"}
        # is_hard の検証を追加 (オプショナルだが、あれば bool)
        if 'is_hard' in rule_data and not isinstance(rule_data['is_hard'], bool):
             return {'rule_type': 'INVALID', 'reason': f"is_hard must be a boolean for {rule_type}"}

    elif rule_type == 'FORBID_SHIFT':
        shift = rule_data.get('shift')
        if not is_valid_shift(shift):
            return {'rule_type': 'INVALID', 'reason': f"Invalid or missing shift symbol for {rule_type}: {shift}"}

    elif rule_type == 'ALLOW_ONLY_SHIFTS':
        allowed = rule_data.get('allowed_shifts')
        if not isinstance(allowed, list) or not all(is_valid_shift(s) for s in allowed):
            return {'rule_type': 'INVALID', 'reason': f"Invalid allowed_shifts for {rule_type}: {allowed}"}

    elif rule_type == 'FORBID_SIMULTANEOUS_SHIFT':
        if not isinstance(rule_data.get('employee2'), str):
             return {'rule_type': 'INVALID', 'reason': f"Missing or invalid employee2 for {rule_type}"}
        shift = rule_data.get('shift')
        if not is_valid_shift(shift):
             return {'rule_type': 'INVALID', 'reason': f"Invalid or missing shift symbol for {rule_type}: {shift}"}

    elif rule_type == 'TOTAL_SHIFT_COUNT':
        shifts_list = rule_data.get('shifts')
        if not isinstance(shifts_list, list) or not all(is_valid_shift(s) for s in shifts_list):
             return {'rule_type': 'INVALID', 'reason': f"Invalid shifts list for {rule_type}: {shifts_list}"}
        min_val = rule_data.get('min')
        max_val = rule_data.get('max')
        if min_val is None and max_val is None:
             return {'rule_type': 'INVALID', 'reason': f"min or max must be specified for {rule_type}"}
        if min_val is not None and (not isinstance(min_val, int) or min_val < 0):
            return {'rule_type': 'INVALID', 'reason': f"Invalid min value for {rule_type}: {min_val}"}
        if max_val is not None and (not isinstance(max_val, int) or max_val < 0):
             return {'rule_type': 'INVALID', 'reason': f"Invalid max value for {rule_type}: {max_val}"}
        if min_val is not None and max_val is not None and min_val > max_val:
            return {'rule_type': 'INVALID', 'reason': f"min > max for {rule_type}: min={min_val}, max={max_val}"}
        # is_hard の検証を追加 (オプショナルだが、あれば bool)
        if 'is_hard' in rule_data and not isinstance(rule_data['is_hard'], bool):
             return {'rule_type': 'INVALID', 'reason': f"is_hard must be a boolean for {rule_type}"}

    elif rule_type == 'PREFER_WEEKDAY_SHIFT': # PREFER_WEEKDAY_SHIFT の検証を追加 (weightはオプショナル)
         if not isinstance(rule_data.get('weekday'), int) or not (0 <= rule_data['weekday'] <= 6):
             return {'rule_type': 'INVALID', 'reason': f"Invalid weekday for {rule_type}: {rule_data.get('weekday')}"}
         shift = rule_data.get('shift')
         if not is_valid_shift(shift):
             return {'rule_type': 'INVALID', 'reason': f"Invalid or missing shift symbol for {rule_type}: {shift}"}
         weight = rule_data.get('weight')
         if weight is not None and not isinstance(weight, (int, float)):
             return {'rule_type': 'INVALID', 'reason': f"Invalid weight for {rule_type}: {weight}"}
         # is_hard の検証を追加 (オプショナルだが、あれば bool)
         if 'is_hard' in rule_data and not isinstance(rule_data['is_hard'], bool):
             return {'rule_type': 'INVALID', 'reason': f"is_hard must be a boolean for {rule_type}"}

    elif rule_type == 'MAX_CONSECUTIVE_OFF':
        if not isinstance(rule_data.get('max_days'), int) or rule_data['max_days'] <= 0:
             return {'rule_type': 'INVALID', 'reason': f"Invalid max_days for {rule_type}: {rule_data.get('max_days')}"}
        # is_hard の検証を追加 (オプショナルだが、あれば bool)
        if 'is_hard' in rule_data and not isinstance(rule_data['is_hard'], bool):
             return {'rule_type': 'INVALID', 'reason': f"is_hard must be a boolean for {rule_type}"}

    elif rule_type == 'FORBID_SHIFT_SEQUENCE':
        pre_shift = rule_data.get('preceding_shift')
        sub_shift = rule_data.get('subsequent_shift')
        if not is_valid_shift(pre_shift) or not is_valid_shift(sub_shift):
            return {'rule_type': 'INVALID', 'reason': f"Invalid shift symbols for {rule_type}: {pre_shift} -> {sub_shift}"}

    elif rule_type == 'ENFORCE_SHIFT_SEQUENCE':
        pre_shift = rule_data.get('preceding_shift')
        sub_shift = rule_data.get('subsequent_shift')
        if not is_valid_shift(pre_shift) or not is_valid_shift(sub_shift):
            return {'rule_type': 'INVALID', 'reason': f"Invalid shift symbols for {rule_type}: {pre_shift} -> {sub_shift}"}

    # PREFER_CALENDAR_SCHEDULE は削除されたので検証不要
    # MAX_CONSECUTIVE_OFF も現在AI解釈対象外なので検証不要

    else: # 未知のルールタイプ
        return {'rule_type': 'INVALID', 'reason': f"Unknown rule_type: {rule_type}"}

    # 特に問題なければ、元のデータを（日付変換などを適用して）返す
    return rule_data

def parse_structured_rules_from_ai(ai_output_dict, start_date, end_date):
    """
    AIが出力した(と仮定する)辞書を解析し、
    検証済みの構造化ルールデータ(辞書)のリストを返す。
    日付の検証には start_date, end_date を使用する。
    """
    all_structured_rules = []
    if not isinstance(ai_output_dict, dict):
        print("エラー(パーサー): AI出力が辞書形式ではありません。")
        return all_structured_rules

    for employee_id, rules_list in ai_output_dict.items():
        if not isinstance(rules_list, list):
             print(f"警告(パーサー): {employee_id} のルールがリスト形式ではありません。スキップします。")
             continue
        for rule_object in rules_list:
            if isinstance(rule_object, dict) and 'structured_data' in rule_object:
                structured_data = rule_object['structured_data']
                # 検証と変換 (start_date, end_date を渡す)
                validated_rule = validate_and_transform_rule(structured_data, start_date, end_date)
                if validated_rule.get('rule_type') == 'INVALID':
                    # 元のデータもログに出力するとデバッグしやすい
                    print(f"警告(パーサー): 無効なルールデータをスキップ: {validated_rule.get('reason')} - Original: {rule_object.get('structured_data')}")
                elif validated_rule.get('rule_type') == 'UNPARSABLE':
                     print(f"情報(パーサー): AIが解釈不能としたルール: {validated_rule}")
                     all_structured_rules.append(validated_rule) # 解釈不能情報も渡す
                else: # VALID
                    print(f"情報(パーサー): 有効なルールを追加: {validated_rule}")
                    all_structured_rules.append(validated_rule)
            else:
                 print(f"警告(パーサー): 不正なルールオブジェクト形式: {rule_object}")

    # 処理されたルール数を表示 (INVALID除く)
    valid_rule_count = sum(1 for r in all_structured_rules if r.get('rule_type') not in ['INVALID', 'UNPARSABLE'])
    unparsable_count = sum(1 for r in all_structured_rules if r.get('rule_type') == 'UNPARSABLE')
    print(f"{valid_rule_count} valid rules and {unparsable_count} unparsable rules extracted.")

    return all_structured_rules

# --- 古い関数は削除 ---
# def parse_shaped_rule(...):
# def parse_shaped_rules(...): 