# メイン実行スクリプト
import sys
import pandas as pd # 過去シフト転記で必要
from datetime import timedelta # 過去シフト転記で必要
import google.generativeai as genai
import os
import json
from dotenv import load_dotenv

# src ディレクトリを Python パスに追加 (環境によっては不要な場合もある)
# import os
# sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.constants import (
    EMPLOYEE_INFO_FILE, PAST_SHIFT_FILE, OUTPUT_DIR,
    START_DATE, END_DATE,
    # AI関連の定数を追加 (必要なら)
    AI_PROMPT_FILE, AI_MODEL_NAME
)
from src.data_loader import load_employee_data, load_past_shifts, load_natural_language_rules
from src.utils import get_date_range, get_holidays, get_employee_indices
from src.shift_model import build_shift_model
from src.solver import solve_shift_model
from src.output_processor import create_shift_dataframe, process_solver_results, save_shift_to_csv
from src.rule_parser import parse_structured_rules_from_ai

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

def call_ai_to_structure_rules(natural_language_rules: dict, prompt_template: str, target_year: int) -> dict | None:
    """自然言語ルールをAIに渡し、構造化されたJSON(辞書)を返す (対象年を再度追加)"""
    if not api_key:
        print("AI処理スキップ: APIキーが設定されていません。")
        return None
    if not prompt_template:
        print("AI処理スキップ: プロンプトテンプレートが読み込めませんでした。")
        return None
    if not natural_language_rules:
        print("AI処理スキップ: 入力ルールが空です。")
        return {}

    # ログ表示を修正
    print(f"Calling AI to structure rules (Target Year: {target_year})...")
    input_rules_text = format_rules_for_prompt(natural_language_rules)
    try:
        # target_year もフォーマットに渡す
        final_prompt = prompt_template.format(input_csv_data=input_rules_text, target_year=target_year)
        # print("--- Final Prompt (partial) ---") # デバッグ用
        # print(final_prompt[:500] + "...")
    except KeyError as e:
        print(f"エラー: プロンプトのフォーマット中にキーエラー: '{e}' が見つかりません。プロンプトファイルを確認してください。")
        return None
    except Exception as e:
        print(f"エラー: プロンプトのフォーマット中にエラーが発生しました: {e}")
        return None

    try:
        model = genai.GenerativeModel(AI_MODEL_NAME)
        response = model.generate_content(final_prompt)
        response_text = response.text
        # --- AI応答の生ログを追加 ---
        print("--- Raw AI Response ---")
        print(response_text)
        # --- AI応答の生ログを追加ここまで ---

        # 応答テキストからJSON部分を抽出・パース
        json_block_start = response_text.find("```json")
        json_block_end = response_text.rfind("```")
        if json_block_start != -1 and json_block_end != -1 and json_block_start < json_block_end:
            json_string = response_text[json_block_start + 7 : json_block_end].strip()
            parsed_json = json.loads(json_string)
            print("AI rule structuring successful.")
            return parsed_json
        else:
            print("警告: AI応答から ```json ブロックが見つかりませんでした。全体をパース試行します。")
            try:
                 parsed_json = json.loads(response_text)
                 print("AI rule structuring successful (parsed whole response).")
                 return parsed_json
            except json.JSONDecodeError:
                 print("エラー: AI応答のJSONパースに失敗しました。")
                 print("--- Raw AI Response --- ")
                 print(response_text)
                 return None

    except Exception as e:
        print(f"エラー: Gemini API呼び出しまたは結果処理中にエラーが発生しました: {e}")
        return None

# --- ここまで AI 関連処理 ---

def main():
    """メイン処理"""
    print("--- Shift Generator Script Start ---")

    # 1. データの読み込みと準備
    print("Loading base data...")
    employees_df = load_employee_data(EMPLOYEE_INFO_FILE)
    past_shifts_df = load_past_shifts(PAST_SHIFT_FILE, START_DATE)
    # 自然言語ルールを読み込み (職員ID -> ルール文字列 の辞書)
    natural_language_rules = load_natural_language_rules()

    if employees_df is None:
        print("エラー: 従業員情報の読み込みに失敗しました。処理を中断します。")
        sys.exit(1)
    if not natural_language_rules:
         print("情報: 自然言語ルールが見つかりませんでした。AI処理はスキップされます。")

    # target_year を再度取得
    target_year = START_DATE.year
    date_range = get_date_range(START_DATE, END_DATE)
    jp_holidays = get_holidays(START_DATE.year, END_DATE.year)
    employee_ids, emp_id_to_row_index = get_employee_indices(employees_df)

    # 2. AIによるルール構造化
    print("\n--- Step 2: AI Rule Structuring ---")
    ai_structured_rules_dict = None
    # プロンプトテンプレートを読み込む (エスケープ処理は削除)
    prompt_template = load_prompt(AI_PROMPT_FILE)
    if api_key and prompt_template and natural_language_rules:
        # AI呼び出しを実行 (対象年を再度渡す)
        ai_structured_rules_dict = call_ai_to_structure_rules(natural_language_rules, prompt_template, target_year)
    else:
        print("Skipping AI rule structuring due to missing API key, prompt, or rules.")

    # 3. ルールパーサーの実行 (START_DATE, END_DATE を渡す)
    print("\n--- Step 3: Rule Parsing ---")
    structured_rules = [] # パース結果を格納するリスト
    if ai_structured_rules_dict is not None:
        structured_rules = parse_structured_rules_from_ai(ai_structured_rules_dict, START_DATE, END_DATE)
        # メッセージは変更
        # print(f"Successfully parsed {len(structured_rules)} rules from AI output.")
    else:
        print("Skipping rule parsing as AI structuring was skipped or failed.")
        # AI処理がない場合、ここにデフォルトルールや他のルールソースからの処理を追加することも可能

    # 4. OR-Toolsモデルの構築 (パース済み構造化ルールを使用)
    print("\n--- Step 4: Building OR-Tools Model ---")
    model, shifts_vars, employee_ids_from_model, date_range_from_model = build_shift_model(
        employees_df=employees_df,
        past_shifts_df=past_shifts_df,
        date_range=date_range,
        jp_holidays=jp_holidays,
        structured_rules=structured_rules # パース結果を渡す
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