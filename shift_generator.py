# メイン実行スクリプト
import sys
import pandas as pd # 過去シフト転記で必要
from datetime import timedelta, date # 日付処理と祝日展開で追加
import google.generativeai as genai
import os
import json
from dotenv import load_dotenv
import re

# src ディレクトリを Python パスに追加 (環境によっては不要な場合もある)
# import os
# sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.constants import (
    EMPLOYEE_INFO_FILE, PAST_SHIFT_FILE, OUTPUT_DIR,
    START_DATE, END_DATE,
    # AI関連の定数を更新
    # AI_PROMPT_FILE, # 古い個人ルールプロンプトは削除またはコメントアウト
    PERSONAL_INTERMEDIATE_PROMPT_FILE, # 個人Step1用
    PERSONAL_STRUCTURED_DATA_PROMPT_FILE, # 個人Step2用
    AI_MODEL_NAME,
    FACILITY_INTERMEDIATE_PROMPT_FILE, # 施設Step1用
    FACILITY_STRUCTURED_DATA_PROMPT_FILE # 施設Step2用
)
from src.data_loader import load_employee_data, load_past_shifts, load_natural_language_rules, load_facility_rules
from src.utils import get_date_range, get_holidays, get_employee_indices
from src.shift_model import build_shift_model
from src.solver import solve_shift_model
from src.output_processor import create_shift_dataframe, process_solver_results, save_shift_to_csv
# from src.rule_parser import parse_structured_rules_from_ai, validate_facility_rule # parse_structured_rules_from_ai は main 内で処理するように変更
from src.rule_parser import validate_and_transform_rule, validate_facility_rule # 検証関数を直接使う

# --- AI 関連処理 --- (ai_rule_experiment.py から移植・統合)

# .envファイルから環境変数を読み込む
load_dotenv()

# APIキーを設定 (環境変数 GEMINI_API_KEY を設定してください)
api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    try:
        genai.configure(api_key=api_key)
        print("Gemini API Key configured.")
    except Exception as e:
        print(f"警告: Gemini APIキーの設定に失敗しました: {e}")
        api_key = None # APIキーが無効な場合はNoneにしておく
else:
    print("警告: 環境変数 'GEMINI_API_KEY' が設定されていません。AIルール解釈はスキップされます。")

def load_prompt(file_path: str) -> str | None:
    """プロンプトファイルを読み込む"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            prompt = f.read()
        return prompt
    except FileNotFoundError:
        print(f"エラー: プロンプトファイルが見つかりません: {file_path}")
        return None
    except Exception as e:
        print(f"エラー: プロンプトファイルの読み込み中にエラーが発生しました: {e}")
        return None

def format_rules_for_prompt(rules_dict: dict) -> str:
    """職員IDと言語ルールの辞書をプロンプト用のCSV形式文字列に変換"""
    lines = ["職員ID,ルール・希望 (自然言語)"]
    for emp_id, rule_text in rules_dict.items():
        escaped_rule_text = str(rule_text).replace('"', '""') if rule_text else "" # 空の場合も考慮
        lines.append(f"{emp_id},\"{escaped_rule_text}\"")
    return "\n".join(lines)

# --- 個人ルール用AI呼び出し関数 (ステップ1: 中間翻訳) ---
def call_ai_to_translate_personal_rules(natural_language_rules: dict, prompt_template: str, target_year: int) -> str | None:
    """自然言語の個人ルール辞書をAIに渡し、(必須)/(推奨)付き確認用文章(改行区切りテキスト)を返す"""
    if not api_key or not prompt_template or not natural_language_rules:
        print("AI処理スキップ(個人 Step1): APIキー、プロンプト、または入力ルールが不足しています。")
        return None

    # # ★デバッグ: AIに渡すルールを最初の15件に制限
    # import itertools
    # limited_rules = dict(itertools.islice(natural_language_rules.items(), 15))
    # print(f"DEBUG: Limiting personal rules to first {len(limited_rules)} entries for AI prompt.")

    print(f"Calling AI for Step 1: Translating personal rules (Target Year: {target_year})...")
    input_rules_text = format_rules_for_prompt(natural_language_rules) # ★修正: natural_language_rules を使用
    try:
        final_prompt = prompt_template.replace("{input_csv_data}", input_rules_text).replace("{target_year}", str(target_year))
    except Exception as e:
        print(f"エラー(個人 Step1): プロンプトのフォーマット中にエラーが発生しました: {e}")
        return None

    try:
        model = genai.GenerativeModel(AI_MODEL_NAME)
        response = model.generate_content(final_prompt)
        intermediate_texts = response.text.strip()
        print("--- Raw AI Response (Personal Step 1: Intermediate Texts) ---")
        print(intermediate_texts)
        if intermediate_texts:
            print("AI personal rule translation successful.")
            return intermediate_texts
        else:
            print("警告(個人 Step1): AIからの応答が空でした。")
            return None
    except Exception as e:
        print(f"エラー(個人 Step1): Gemini API呼び出しまたは結果処理中にエラーが発生しました: {e}")
        return None

# --- 個人ルール用AI呼び出し関数 (ステップ2: structured_data生成) ---
def call_ai_to_generate_structured_data_personal(intermediate_texts: str, prompt_template: str, target_year: int) -> str | None:
    """(必須)/(推奨)付き確認用文章テキストをAIに渡し、職員IDごとのstructured_data辞書のJSON文字列を返す"""
    if not api_key or not prompt_template or not intermediate_texts:
        print("AI処理スキップ(個人 Step2): APIキー、プロンプト、または入力テキストが不足しています。")
        return None

    print(f"Calling AI for Step 2: Generating structured_data dictionary (Target Year: {target_year})...")
    try:
        final_prompt = prompt_template.replace("{intermediate_confirmation_texts}", intermediate_texts).replace("{target_year}", str(target_year))
    except Exception as e:
        print(f"エラー(個人 Step2): プロンプトのフォーマット中にエラーが発生しました: {e}")
        return None

    try:
        model = genai.GenerativeModel(AI_MODEL_NAME)
        response = model.generate_content(final_prompt)
        structured_data_dict_str = response.text
        print("--- Raw AI Response (Personal Step 2: Structured Data Dictionary String) ---")
        print(structured_data_dict_str)
        if structured_data_dict_str:
            print("AI personal structured_data generation successful.")
            return structured_data_dict_str
        else:
            print("警告(個人 Step2): AIからの応答が空でした。")
            return None
    except Exception as e:
        print(f"エラー(個人 Step2): Gemini API呼び出しまたは結果処理中にエラーが発生しました: {e}")
        return None

# --- 施設ルール用AI呼び出し関数 (ステップ1: 中間翻訳) ---
def call_ai_to_translate_facility_rules(facility_rules_list: list[str], prompt_template: str, target_year: int) -> str | None:
    """自然言語の施設ルールリストをAIに渡し、(必須)/(推奨)付き確認用文章(改行区切りテキスト)を返す"""
    if not api_key or not prompt_template or not facility_rules_list:
        print("AI処理スキップ(施設 Step1): APIキー、プロンプト、または入力ルールが不足しています。")
        return None

    print(f"Calling AI for Step 1: Translating facility rules to confirmation texts (Target Year: {target_year})...")
    input_rules_text = "\n".join(facility_rules_list)
    try:
        # ステップ1プロンプトのプレースホルダーは {facility_rules_text} と {target_year} と想定
        # .format() の代わりに replace() を使用
        final_prompt = prompt_template.replace(
            "{facility_rules_text}", input_rules_text
        ).replace(
            "{target_year}", str(target_year)
        )
    except Exception as e:
        print(f"エラー(施設 Step1): プロンプトのフォーマット中にエラーが発生しました: {e}")
        return None

    try:
        model = genai.GenerativeModel(AI_MODEL_NAME)
        response = model.generate_content(final_prompt)
        # AIは確認用文章を改行区切りで返す想定
        intermediate_texts = response.text.strip()
        print("--- Raw AI Response (Facility Step 1: Intermediate Texts) ---")
        print(intermediate_texts)
        if intermediate_texts:
             print("AI facility rule translation successful.")
             return intermediate_texts
        else:
             print("警告(施設 Step1): AIからの応答が空でした。")
             return None
    except Exception as e:
        print(f"エラー(施設 Step1): Gemini API呼び出しまたは結果処理中にエラーが発生しました: {e}")
        return None

# --- 施設ルール用AI呼び出し関数 (ステップ2: structured_data生成) ---
def call_ai_to_generate_structured_data(intermediate_texts: str, prompt_template: str, target_year: int) -> str | None:
    """(必須)/(推奨)付き確認用文章テキストをAIに渡し、structured_dataのJSONリスト文字列を返す"""
    if not api_key or not prompt_template or not intermediate_texts:
        print("AI処理スキップ(施設 Step2): APIキー、プロンプト、または入力テキストが不足しています。")
        return None

    print(f"Calling AI for Step 2: Generating structured_data JSON list (Target Year: {target_year})...")
    try:
        # ステップ2プロンプトのプレースホルダーは {intermediate_confirmation_texts} と {target_year} と想定
        # .format() の代わりに replace() を使用
        final_prompt = prompt_template.replace(
            "{intermediate_confirmation_texts}", intermediate_texts
        ).replace(
            "{target_year}", str(target_year)
        )
    except Exception as e:
        print(f"エラー(施設 Step2): プロンプトのフォーマット中にエラーが発生しました: {e}")
        return None

    try:
        model = genai.GenerativeModel(AI_MODEL_NAME)
        response = model.generate_content(final_prompt)
        # AIはstructured_dataのJSONリスト文字列を返す想定
        structured_data_json_list_str = response.text
        print("--- Raw AI Response (Facility Step 2: Structured Data JSON List String) ---")
        print(structured_data_json_list_str)
        if structured_data_json_list_str:
            print("AI structured_data generation successful.")
            return structured_data_json_list_str
        else:
            print("警告(施設 Step2): AIからの応答が空でした。")
            return None
    except Exception as e:
        print(f"エラー(施設 Step2): Gemini API呼び出しまたは結果処理中にエラーが発生しました: {e}")
        return None

# --- ここまで AI 関連処理 ---

def main():
    """メイン処理"""
    print("--- Shift Generator Script Start ---")

    # 1. データの読み込みと準備
    print("Loading base data...")
    employees_df = load_employee_data(EMPLOYEE_INFO_FILE)
    # ★デバッグ: 読み込み直後の行数を表示
    if employees_df is not None:
        print(f"DEBUG: employees_df loaded with {len(employees_df)} rows.")
    else:
        print("DEBUG: employees_df is None after loading.")

    past_shifts_df = load_past_shifts(PAST_SHIFT_FILE, START_DATE)
    natural_language_rules = load_natural_language_rules()
    facility_rules_list = load_facility_rules()

    if employees_df is None:
        print("エラー: 従業員情報の読み込みに失敗しました。処理を中断します。")
        sys.exit(1)
    if not natural_language_rules: print("情報: 個人ルールが見つかりませんでした。")
    if not facility_rules_list: print("情報: 施設ルールが見つかりませんでした。")

    target_year = START_DATE.year
    date_range = get_date_range(START_DATE, END_DATE)
    jp_holidays = get_holidays(START_DATE.year, END_DATE.year)
    employee_ids, emp_id_to_row_index = get_employee_indices(employees_df)
    # ★デバッグ: get_employee_indices 後の要素数を表示
    print(f"DEBUG: employee_ids generated with {len(employee_ids)} elements.")

    # 2. AIによるルール構造化 (個人 & 施設 - 2ステップ化)
    print("\n--- Step 2: AI Rule Structuring ---")
    intermediate_personal_texts = None
    structured_data_dict_personal = {} # 初期化
    intermediate_facility_texts = None
    structured_data_list_facility = [] # 初期化

    # --- 個人ルールAI処理 (2ステップ) --- 
    # ステップ1: 中間翻訳
    personal_intermediate_prompt = load_prompt(PERSONAL_INTERMEDIATE_PROMPT_FILE)
    if api_key and personal_intermediate_prompt and natural_language_rules:
        intermediate_personal_texts = call_ai_to_translate_personal_rules(natural_language_rules, personal_intermediate_prompt, target_year)
    else:
        print("Skipping AI personal rule structuring (Step 1).")

    # (オプション) 個人ルールの中間確認・修正
    # if intermediate_personal_texts:
    #     print("\n--- 個人ルール 中間確認用文章 (修正可能) ---")
    #     print(intermediate_personal_texts)

    # ステップ2: structured_data生成
    personal_structured_data_prompt = load_prompt(PERSONAL_STRUCTURED_DATA_PROMPT_FILE)
    if api_key and personal_structured_data_prompt and intermediate_personal_texts:
        structured_data_dict_str = call_ai_to_generate_structured_data_personal(intermediate_personal_texts, personal_structured_data_prompt, target_year)
        if structured_data_dict_str:
            # クリーニング & パース
            cleaned_json_string = structured_data_dict_str.strip()
            if cleaned_json_string.startswith("```json"):
                cleaned_json_string = cleaned_json_string[7:]
            if cleaned_json_string.endswith("```"):
                cleaned_json_string = cleaned_json_string[:-3]
            cleaned_json_string = cleaned_json_string.strip()
            try:
                structured_data_dict_personal = json.loads(cleaned_json_string)
                if not isinstance(structured_data_dict_personal, dict):
                    print(f"エラー(個人 Step2): パース結果が辞書形式ではありません。")
                    structured_data_dict_personal = {}
            except json.JSONDecodeError as e:
                print(f"エラー(個人 Step2): JSON辞書のパースに失敗: {e}")
                print(f"クリーニング後の文字列:\n{cleaned_json_string}")
                structured_data_dict_personal = {}
        else:
             print("Skipping personal rule structuring (Step 2) due to empty response from AI.")
    else:
        print("Skipping AI personal rule structuring (Step 2).")
    # --- 個人ルールAI処理ここまで --- 

    # --- 施設ルールAI処理 (2ステップ - 変更なし) ---
    intermediate_prompt = load_prompt(FACILITY_INTERMEDIATE_PROMPT_FILE)
    if api_key and intermediate_prompt and facility_rules_list:
        intermediate_facility_texts = call_ai_to_translate_facility_rules(facility_rules_list, intermediate_prompt, target_year)
    else:
        print("Skipping AI facility rule structuring (Step 1).")
    # ... (オプションのユーザー修正) ...
    structured_data_prompt = load_prompt(FACILITY_STRUCTURED_DATA_PROMPT_FILE)
    if api_key and structured_data_prompt and intermediate_facility_texts:
        structured_data_json_list_str = call_ai_to_generate_structured_data(intermediate_facility_texts, structured_data_prompt, target_year)
        if structured_data_json_list_str:
            # ... (クリーニング & パース - 変更なし) ...
            cleaned_json_string = structured_data_json_list_str.strip()
            if cleaned_json_string.startswith("```json"):
                cleaned_json_string = cleaned_json_string[7:]
            if cleaned_json_string.endswith("```"):
                cleaned_json_string = cleaned_json_string[:-3]
            cleaned_json_string = cleaned_json_string.strip()
            try:
                structured_data_list_facility = json.loads(cleaned_json_string)
                if not isinstance(structured_data_list_facility, list):
                    print(f"エラー(施設 Step2): パース結果がリスト形式ではありません。")
                    structured_data_list_facility = []
            except json.JSONDecodeError as e:
                print(f"エラー(施設 Step2): JSONリストのパースに失敗: {e}")
                print(f"クリーニング後の文字列:\n{cleaned_json_string}")
                structured_data_list_facility = []
        else:
            print("Skipping facility rule structuring (Step 2) due to empty response from AI.")
    else:
        print("Skipping AI facility rule structuring (Step 2).")
    # --- 施設ルールAI処理ここまで ---

    # 3. ルールパーサーの実行 & 最終リスト構築 & 祝日展開
    print("\n--- Step 3: Rule Parsing & Final List Construction ---")
    personal_final_rules = [] # 最終的な個人ルールリスト
    facility_final_rules = [] # 最終的な施設ルールリスト

    # 個人ルールのパースと検証、祝日展開
    if structured_data_dict_personal:
        print(f"\nProcessing final personal rules...")
        valid_count_p = 0
        invalid_count_p = 0
        unparsable_count_p = 0
        holiday_rules_generated = 0
        for employee_id, rules_list in structured_data_dict_personal.items():
            if not isinstance(rules_list, list):
                print(f"  警告(個人ルール構築): {employee_id} のルールがリスト形式ではありません。スキップします。")
                continue
            for struct_data in rules_list:
                 # 特別な祝日ルールの処理
                 if isinstance(struct_data, dict) and struct_data.get('rule_type') == 'PREFER_ALL_HOLIDAYS_OFF':
                     print(f"  情報(個人ルール構築): 祝日ルール展開中 for {employee_id}...")
                     holiday_shift = struct_data.get('shift', '公') # デフォルトは公休
                     holiday_is_hard = struct_data.get('is_hard', False) # デフォルトは推奨
                     for holiday_date in jp_holidays:
                         if START_DATE <= holiday_date <= END_DATE:
                             holiday_rule = {
                                 "rule_type": "SPECIFY_DATE_SHIFT",
                                 "employee": employee_id,
                                 "date": holiday_date.isoformat(), # ★修正: dateオブジェクトをISO形式文字列に変換
                                 "shift": holiday_shift,
                                 "is_hard": holiday_is_hard
                             }
                             # この生成されたルールも検証する
                             validated_holiday_rule = validate_and_transform_rule(holiday_rule, START_DATE, END_DATE)
                             if validated_holiday_rule.get('rule_type') != 'INVALID':
                                 # 検証成功後、dateはdateオブジェクトになっているはず
                                 personal_final_rules.append(validated_holiday_rule)
                                 holiday_rules_generated += 1
                                 print(f"    -> 生成・追加(祝日): {validated_holiday_rule}")
                             else:
                                 print(f"    -> 警告(祝日ルール生成): 生成ルール検証NG: {validated_holiday_rule.get('reason')}")
                     continue # 元の PREFER_ALL_HOLIDAYS_OFF は追加しない

                 # 通常ルールの検証
                 validated_rule = validate_and_transform_rule(struct_data, START_DATE, END_DATE)
                 if validated_rule.get('rule_type') == 'INVALID':
                    print(f"  警告(個人ルール構築): 検証NGルールをスキップ: {validated_rule.get('reason')} - Employee: {employee_id}, Original Data: {struct_data}")
                    invalid_count_p += 1
                 elif validated_rule.get('rule_type') == 'UNPARSABLE':
                     print(f"  情報(個人ルール構築): AI解釈不能ルールを追加: {validated_rule}")
                     personal_final_rules.append(validated_rule)
                     unparsable_count_p += 1
                 else: # VALID
                     personal_final_rules.append(validated_rule)
                     print(f"  情報(個人ルール構築): ルール追加: {validated_rule}")
                     valid_count_p += 1
        print(f"{valid_count_p} valid personal rules processed, {holiday_rules_generated} holiday rules generated, {unparsable_count_p} unparsable rules added, {invalid_count_p} rules skipped due to validation errors.")
    else:
        print("Skipping personal rule final list construction.")

    # 施設ルールの最終リスト構築と検証
    if intermediate_facility_texts and structured_data_list_facility:
        # ★修正: split後に空行を除去する
        intermediate_lines = [line for line in intermediate_facility_texts.strip().split('\n') if line.strip()]
        if len(intermediate_lines) == len(structured_data_list_facility):
            print(f"\nConstructing final facility rules...")
            valid_count_f = 0
            invalid_count_f = 0
            unparsable_count_f = 0
            for conf_text, struct_data in zip(intermediate_lines, structured_data_list_facility):
                validated_rule = validate_facility_rule(struct_data, START_DATE, END_DATE)
                if validated_rule.get('rule_type') == 'INVALID':
                    print(f"  警告(施設ルール構築): 検証NGルールをスキップ: {validated_rule.get('reason')} - Confirmation: {conf_text.strip()}, Original Data: {struct_data}")
                    invalid_count_f += 1
                elif validated_rule.get('rule_type') == 'UNPARSABLE':
                     print(f"  情報(施設ルール構築): AI解釈不能ルールを追加: {validated_rule}")
                     facility_final_rules.append({
                         "confirmation_text": conf_text.strip(),
                         "structured_data": validated_rule
                     })
                     unparsable_count_f += 1
                else: # VALID
                    facility_final_rules.append({
                        "confirmation_text": conf_text.strip(),
                        "structured_data": validated_rule
                    })
                    print(f"  情報(施設ルール構築): ルール追加: {conf_text.strip()} -> {validated_rule}")
                    valid_count_f += 1
            print(f"{valid_count_f} valid facility rules constructed, {unparsable_count_f} unparsable rules added, {invalid_count_f} rules skipped due to validation errors.")
        else:
            print(f"エラー(施設ルール構築): 確認テキストの行数({len(intermediate_lines)})と構造化データ数({len(structured_data_list_facility)})が一致しません。")
    else:
        print("Skipping facility rule final list construction.")

    # 4. OR-Toolsモデルの構築 (最終ルールリストを使用)
    print("\n--- Step 4: Building OR-Tools Model ---")
    model, shifts_vars, employee_ids_from_model, date_range_from_model = build_shift_model(
        employees_df=employees_df,
        past_shifts_df=past_shifts_df,
        date_range=date_range,
        jp_holidays=jp_holidays,
        personal_rules=personal_final_rules, # 構築した個人ルールリスト
        facility_rules=facility_final_rules # 構築した施設ルールリスト
    )

    # 5. ソルバーの実行 (変更なし)
    print("\n--- Step 5: Solving the Model ---")
    status, solver = solve_shift_model(model)

    # 6. 結果の処理と出力 (変更なし)
    print("\n--- Step 6: Processing Results ---")
    initial_shift_df = create_shift_dataframe(employees_df, date_range, jp_holidays)
    if initial_shift_df is None:
         print("エラー: 出力用DataFrameの初期化に失敗。")
         sys.exit(1)
    if past_shifts_df is not None:
        # ... (過去シフト転記 - 変更なし) ...
        pass
    final_shift_df = process_solver_results(status, solver, shifts_vars, employee_ids, date_range, initial_shift_df, employees_df, jp_holidays)
    if final_shift_df is not None:
        save_shift_to_csv(final_shift_df, OUTPUT_DIR, START_DATE)
        print("\nShift generation complete. Output saved.")
    else:
        print("\nエラー: シフト生成に失敗したため、CSVファイルは出力されませんでした。")

    print("--- Shift Generator Script End ---")

if __name__ == "__main__":
    main() 