# 整形済み定型文ルールパーサー
import json # JSON形式を扱う場合 (今回はPython辞書を直接扱う)
from datetime import date

# SHIFT_MAP_INT は日付以外のパラメータ検証で使えるかもしれない
from src.constants import SHIFT_MAP_INT

def validate_and_transform_rule(rule_data):
    """
    単一の構造化ルールデータ(辞書)を検証し、必要なら変換する。
    無効な場合は rule_type を 'INVALID' にして返す。
    """
    if not isinstance(rule_data, dict):
        return {'rule_type': 'INVALID', 'reason': 'Data is not a dictionary.'}

    rule_type = rule_data.get('rule_type')
    employee = rule_data.get('employee') or rule_data.get('employee1')

    if not rule_type or not employee:
        return {'rule_type': 'INVALID', 'reason': 'Missing rule_type or employee/employee1.'}

    # 日付文字列を date オブジェクトに変換 (存在する場合)
    if 'date' in rule_data and isinstance(rule_data['date'], str):
        try:
            rule_data['date'] = date.fromisoformat(rule_data['date'])
        except ValueError:
            return {'rule_type': 'INVALID', 'reason': f"Invalid date format: {rule_data['date']}"}

    # 簡単な型チェックや必須パラメータの存在チェックなど (必要に応じて追加)
    # 例: MAX_CONSECUTIVE_WORK なら max_days が整数か？
    if rule_type == 'MAX_CONSECUTIVE_WORK' and not isinstance(rule_data.get('max_days'), int):
         return {'rule_type': 'INVALID', 'reason': f"Invalid max_days for {rule_type}"}
    # 他の rule_type についても同様にチェックを追加可能

    # 特に問題なければ、元のデータを（日付変換などを適用して）返す
    return rule_data

def parse_structured_rules_from_ai(ai_output_dict):
    """
    AIが出力した(と仮定する)辞書を解析し、
    検証済みの構造化ルールデータ(辞書)のリストを返す。
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
                # 検証と変換
                validated_rule = validate_and_transform_rule(structured_data)
                if validated_rule.get('rule_type') == 'INVALID':
                    print(f"警告(パーサー): 無効なルールデータをスキップ: {validated_rule.get('reason')} - Original: {rule_object}")
                elif validated_rule.get('rule_type') == 'UNPARSABLE':
                     print(f"情報(パーサー): AIが解釈不能としたルール: {validated_rule}")
                     all_structured_rules.append(validated_rule) # 解釈不能情報も渡す
                elif validated_rule.get('rule_type') != 'PARSE_ERROR': # パーサー自身のエラー以外
                    all_structured_rules.append(validated_rule)
            else:
                 print(f"警告(パーサー): 不正なルールオブジェクト形式: {rule_object}")

    print(f"{len(all_structured_rules)} structured rules extracted and validated.")
    return all_structured_rules

# --- 古い関数は削除 ---
# def parse_shaped_rule(...):
# def parse_shaped_rules(...): 