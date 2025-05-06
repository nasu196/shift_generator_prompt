# メイン実行スクリプト
import sys
import pandas as pd # 過去シフト転記で必要
from datetime import timedelta # 過去シフト転記で必要
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
    # AI関連の定数を追加 (必要なら)
    AI_PROMPT_FILE, AI_MODEL_NAME,
    FACILITY_AI_PROMPT_FILE
)
from src.data_loader import load_employee_data, load_past_shifts, load_natural_language_rules, load_facility_rules
from src.utils import get_date_range, get_holidays, get_employee_indices
from src.shift_model import build_shift_model
from src.solver import solve_shift_model
from src.output_processor import create_shift_dataframe, process_solver_results, save_shift_to_csv
from src.rule_parser import parse_structured_rules_from_ai, parse_facility_rules_from_ai

# --- AI 関連処理 (ai_rule_experiment.py から移植・統合) ---

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
    """プロンプトファイルを読み込む (エスケープ処理は削除)"""
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
        # ルール内のダブルクォートをエスケープ
        escaped_rule_text = str(rule_text).replace('"', '""')
        lines.append(f"{emp_id},\"{escaped_rule_text}\"")
    return "\n".join(lines)

def call_ai_to_structure_personal_rules(natural_language_rules: dict, prompt_template: str, target_year: int) -> dict | None:
    """個人ルールをAIに渡し、構造化されたJSON(辞書)を返す"""
    if not api_key:
        print("AI処理スキップ(個人): APIキーが設定されていません。")
        return None
    if not prompt_template:
        print("AI処理スキップ(個人): プロンプトテンプレートが読み込めませんでした。")
        return None
    if not natural_language_rules:
        print("AI処理スキップ(個人): 入力ルールが空です。")
        return {}

    print(f"Calling AI to structure personal rules (Target Year: {target_year})...")
    input_rules_text = format_rules_for_prompt(natural_language_rules)
    try:
        final_prompt = prompt_template.format(input_csv_data=input_rules_text, target_year=target_year)
    except KeyError as e:
        print(f"エラー(個人): プロンプトのフォーマット中にキーエラー: '{e}' が見つかりません。プロンプトファイルを確認してください。")
        return None
    except Exception as e:
        print(f"エラー(個人): プロンプトのフォーマット中にエラーが発生しました: {e}")
        return None
    try:
        model = genai.GenerativeModel(AI_MODEL_NAME)
        response = model.generate_content(final_prompt)
        response_text = response.text
        print("--- Raw AI Response (Personal) ---")
        print(response_text)
        json_block_start = response_text.find("```json")
        json_block_end = response_text.rfind("```")
        if json_block_start != -1 and json_block_end != -1 and json_block_start < json_block_end:
            json_string = response_text[json_block_start + 7 : json_block_end].strip()
            # --- 末尾のカンマを除去する処理を追加 ---
            # } や ] の直前にあるカンマを削除する (複数行対応)
            cleaned_json_string = re.sub(r'\s*,(\s*[}\]])', r'\1', json_string)
            try:
                parsed_json = json.loads(cleaned_json_string)
                print("AI personal rule structuring successful.")
                return parsed_json
            except json.JSONDecodeError as e_parse:
                 print(f"エラー(個人): JSONパースに失敗しました（カンマ除去後）: {e_parse}")
                 print("--- Cleaned JSON String --- ")
                 print(cleaned_json_string)
                 print("--- Original JSON String --- ")
                 print(json_string)
                 return None
            # --- 末尾のカンマ除去ここまで ---
        else:
            print("警告(個人): AI応答から ```json ブロックが見つかりませんでした。全体をパース試行します。")
            try:
                 parsed_json = json.loads(response_text)
                 print("AI personal rule structuring successful (parsed whole response).")
                 return parsed_json
            except json.JSONDecodeError:
                 print("エラー(個人): AI応答のJSONパースに失敗しました。")
                 print("--- Raw AI Response (Personal) --- ")
                 print(response_text)
                 return None
    except Exception as e:
        print(f"エラー(個人): Gemini API呼び出しまたは結果処理中にエラーが発生しました: {e}")
        return None

# 施設ルール用 AI 呼び出し関数 (新規追加)
def call_ai_to_structure_facility_rules(facility_rules_list: list[str], prompt_template: str, target_year: int) -> list | None:
    """施設ルールリストをAIに渡し、構造化されたJSON(辞書)のリストを返す"""
    if not api_key:
        print("AI処理スキップ(施設): APIキーが設定されていません。")
        return None
    if not prompt_template:
        print("AI処理スキップ(施設): プロンプトテンプレートが読み込めませんでした。")
        return None
    if not facility_rules_list:
        print("AI処理スキップ(施設): 入力ルールが空です。")
        return []

    print(f"Calling AI to structure facility rules (Target Year: {target_year})...")
    # プロンプトに入力ルールを埋め込む (例: 改行区切りのテキストとして)
    input_rules_text = "\n".join(facility_rules_list)
    try:
        # target_year もフォーマットに渡す
        final_prompt = prompt_template.format(input_csv_data=input_rules_text, target_year=target_year)
    except KeyError as e:
        print(f"エラー(施設): プロンプトのフォーマット中にキーエラー: '{e}' が見つかりません。プロンプトファイルを確認してください。")
        return None
    except Exception as e:
        print(f"エラー(施設): プロンプトのフォーマット中にエラーが発生しました: {e}")
        return None

    try:
        model = genai.GenerativeModel(AI_MODEL_NAME)
        response = model.generate_content(final_prompt)
        response_text = response.text
        print("--- Raw AI Response (Facility) ---")
        print(response_text)
        # 施設ルールプロンプトは JSON リストを直接返す想定
        # 個人ルールと同様に ```json ブロックを探すように修正
        json_block_start = response_text.find("```json")
        json_block_end = response_text.rfind("```")
        if json_block_start != -1 and json_block_end != -1 and json_block_start < json_block_end:
             json_string = response_text[json_block_start + 7 : json_block_end].strip()
             parsed_json = json.loads(json_string)
             # パース結果がリストであることを確認
             if isinstance(parsed_json, list):
                 print("AI facility rule structuring successful.")
                 return parsed_json
             else:
                 print(f"エラー(施設): 抽出されたJSONが期待されたリスト形式ではありません (Type: {type(parsed_json)}).")
                 return None
        else:
            print("警告(施設): AI応答から ```json ブロックが見つかりませんでした。全体をパース試行します。")
            try:
                 parsed_json = json.loads(response_text)
                 if isinstance(parsed_json, list):
                      print("AI facility rule structuring successful (parsed whole response).")
                      return parsed_json
                 else:
                      print("エラー(施設): AI応答全体が期待されたリスト形式ではありません。")
                      return None
            except json.JSONDecodeError:
                 print("エラー(施設): AI応答全体のJSONパースに失敗しました。")
                 print("--- Raw AI Response (Facility) --- ")
                 print(response_text)
                 return None
    except Exception as e:
        print(f"エラー(施設): Gemini API呼び出しまたは結果処理中にエラーが発生しました: {e}")
        return None

# --- ここまで AI 関連処理 ---

def main():
    """メイン処理"""
    print("--- Shift Generator Script Start ---")

    # 1. データの読み込みと準備
    print("Loading base data...")
    employees_df = load_employee_data(EMPLOYEE_INFO_FILE)
    past_shifts_df = load_past_shifts(PAST_SHIFT_FILE, START_DATE)
    # 個人ルールを読み込み
    natural_language_rules = load_natural_language_rules()
    # 施設ルールを読み込み (リスト)
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

    # 2. AIによるルール構造化 (個人 & 施設)
    print("\n--- Step 2: AI Rule Structuring ---")
    ai_personal_rules_dict = None
    ai_facility_rules_list = None

    # 個人ルールAI処理
    personal_prompt_template = load_prompt(AI_PROMPT_FILE)
    if api_key and personal_prompt_template and natural_language_rules:
        ai_personal_rules_dict = call_ai_to_structure_personal_rules(natural_language_rules, personal_prompt_template, target_year)
    else:
        print("Skipping AI personal rule structuring.")

    # 施設ルールAI処理
    facility_prompt_template = load_prompt(FACILITY_AI_PROMPT_FILE)
    if api_key and facility_prompt_template and facility_rules_list:
         ai_facility_rules_list = call_ai_to_structure_facility_rules(facility_rules_list, facility_prompt_template, target_year)
    else:
         print("Skipping AI facility rule structuring.")

    # 3. ルールパーサーの実行 (個人 & 施設)
    print("\n--- Step 3: Rule Parsing ---")
    personal_structured_rules = []
    facility_structured_rules = []

    if ai_personal_rules_dict is not None:
        personal_structured_rules = parse_structured_rules_from_ai(ai_personal_rules_dict, START_DATE, END_DATE)
    else:
        print("Skipping personal rule parsing.")

    if ai_facility_rules_list is not None:
         facility_structured_rules = parse_facility_rules_from_ai(ai_facility_rules_list, START_DATE, END_DATE)
    else:
         print("Skipping facility rule parsing.")

    # 4. OR-Toolsモデルの構築 (個人 & 施設ルールを使用)
    print("\n--- Step 4: Building OR-Tools Model ---")
    model, shifts_vars, employee_ids_from_model, date_range_from_model = build_shift_model(
        employees_df=employees_df,
        past_shifts_df=past_shifts_df,
        date_range=date_range,
        jp_holidays=jp_holidays,
        personal_rules=personal_structured_rules, # 引数名を変更
        facility_rules=facility_structured_rules # 引数を追加
    )

    # 5. ソルバーの実行
    print("\n--- Step 5: Solving the Model ---")
    status, solver = solve_shift_model(model)

    # 6. 結果の処理と出力
    print("\n--- Step 6: Processing Results ---")
    # 6.1. 出力用DataFrameの初期化
    initial_shift_df = create_shift_dataframe(employees_df, date_range, jp_holidays)
    if initial_shift_df is None:
         print("エラー: 出力用DataFrameの初期化に失敗。")
         sys.exit(1)

    # 6.2. 過去シフトを出力DFに転記
    if past_shifts_df is not None:
        past_date_cols_input = past_shifts_df.columns[1:].tolist()
        past_date_cols_output = [(START_DATE - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(len(past_date_cols_input), 0, -1)]
        past_shifts_lookup = past_shifts_df.set_index('職員ID')
        employee_data_start_row = 1
        for i, emp_id in enumerate(employee_ids):
            row_idx = employee_data_start_row + i
            if emp_id in past_shifts_lookup.index:
                 for input_col, output_col in zip(past_date_cols_input, past_date_cols_output):
                      initial_shift_df.loc[row_idx, output_col] = past_shifts_lookup.loc[emp_id, input_col]
            else:
                 for output_col in past_date_cols_output:
                      initial_shift_df.loc[row_idx, output_col] = ''

    # 6.3. ソルバー結果を処理してDataFrameに反映
    final_shift_df = process_solver_results(status, solver, shifts_vars, employee_ids, date_range, initial_shift_df, employees_df, jp_holidays)

    # 6.4. CSVに保存
    if final_shift_df is not None:
        save_shift_to_csv(final_shift_df, OUTPUT_DIR, START_DATE)
        print("\nShift generation complete. Output saved.")
    else:
        print("\nエラー: シフト生成に失敗したため、CSVファイルは出力されませんでした。")

    print("--- Shift Generator Script End ---")

if __name__ == "__main__":
    main() 