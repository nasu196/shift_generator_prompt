import google.generativeai as genai
import os
from dotenv import load_dotenv # dotenvライブラリをインポート

# .envファイルから環境変数を読み込む
# この行が実行されると、.envファイル内のキー=値が環境変数として設定される
load_dotenv()

# --- 設定項目 ---
API_KEY = os.environ.get("GEMINI_API_KEY") # 環境変数からAPIキーを取得 (dotenv経由で読み込まれるはず)
TARGET_YEAR = 2025 # ステップ2では直接使わないが、将来的に使う可能性も考慮して残す

# === ステップ1の出力結果を模倣 (前回の成功例を使用) ===
# 実際にはステップ1のAI呼び出し結果をここに渡す
intermediate_confirmation_texts_multiline = """(必須) ALL の 平日 の「日」は最低 3 人必要です。
(必須) 土日祝 は「主任」が最低 1 人出勤します。
(必須) ALL の連続した公休は最大 3 日までです。
(推奨) 常勤 の公休日数を均等化します。
(必須) ALL の「日」の翌日は「早」になります。
(必須) ALL の「早」の翌日は「夜」になります。
(必須) ALL の「夜」の翌日は「明」になります。
(必須) ALL の「明」の翌日は「公」になります。"""
print("--- 入力となる中間確認用文章 (ステップ1の出力模倣) ---")
print(intermediate_confirmation_texts_multiline)
# ======================================================

STEP2_PROMPT_FILE = "prompts/facility_rule_shaping_prompt.md" # ステップ2用のプロンプト

# --- Gemini APIクライアントの設定 ---
if not API_KEY:
    print("エラー: 環境変数 GEMINI_API_KEY が設定されていません。(.envファイルを確認してください)")
    exit()
genai.configure(api_key=API_KEY)
# model = genai.GenerativeModel('gemini-1.5-flash') # 安定性やコストを考慮し、一旦1.5 Flashに戻してテスト (適宜変更可)
model = genai.GenerativeModel('gemini-2.0-flash') # こちらに戻します
print(f"--- 使用モデル: {model._model_name} ---")


# --- ステップ2用プロンプトファイルの読み込み ---
try:
    with open(STEP2_PROMPT_FILE, 'r', encoding='utf-8') as f:
        prompt_template_step2 = f.read()
except FileNotFoundError:
    print(f"エラー: {STEP2_PROMPT_FILE} が見つかりません。")
    exit()

# --- プロンプトの構築 (ステップ2) ---
# {intermediate_confirmation_texts} と {target_year} を単純な文字列置換で埋め込む
final_prompt_step2 = prompt_template_step2.replace(
    "{intermediate_confirmation_texts}", intermediate_confirmation_texts_multiline
).replace(
    "{target_year}", str(TARGET_YEAR) # target_yearも文字列として置換
)

# print("\n--- 生成されたプロンプト (ステップ2: Gemini APIへ送信) ---")
# print(final_prompt_step2) # デバッグ用にプロンプト全体を表示したい場合

# --- Gemini API呼び出し (ステップ2) ---
print(f"\n--- Gemini API呼び出し中 (ステップ2: structured_data 生成) ---")
try:
    response_step2 = model.generate_content(final_prompt_step2)
    ai_output_text = response_step2.text # AIからの生テキストを取得
    print("\n--- AIによる生出力テキスト (structured_dataリストのはず) ---")
    print(ai_output_text)

    # --- AI出力テキストのクリーニング ---
    cleaned_json_string = ai_output_text.strip()
    if cleaned_json_string.startswith("```json"):
        cleaned_json_string = cleaned_json_string[7:] # 先頭の ```json を除去
    if cleaned_json_string.endswith("```"):
        cleaned_json_string = cleaned_json_string[:-3] # 末尾の ``` を除去
    cleaned_json_string = cleaned_json_string.strip() # 前後の空白を除去

    print("\n--- クリーニング後のJSONリスト文字列 ---")
    print(cleaned_json_string)

    # --- JSONリスト全体のパース試行 ---
    print("\n--- JSONリスト全体のパース試行 ---")
    import json
    # rule_parser をインポート (検証用)
    from src.rule_parser import validate_facility_rule
    from src.utils import get_date_range # 検証用に日付範囲も取得
    from src.constants import START_DATE, END_DATE # 検証用に日付定数も取得
    date_range_for_validation = get_date_range(START_DATE, END_DATE) # ダミーの日付範囲

    try:
        structured_data_list = json.loads(cleaned_json_string)
        if isinstance(structured_data_list, list):
            print(f"パース成功: {len(structured_data_list)} 個の structured_data オブジェクトを取得しました。")

            # --- 各structured_dataの検証 (オプション) ---
            print("\n--- 各 structured_data の検証 ---")
            valid_rules = []
            invalid_count = 0
            for i, rule_data in enumerate(structured_data_list):
                 # validate_facility_rule は start_date, end_date を必要とするが、
                 # このテストでは厳密な日付検証は主目的ではないため、定数を使用
                 validated_rule = validate_facility_rule(rule_data, START_DATE, END_DATE)
                 if validated_rule.get('rule_type') == 'INVALID':
                     print(f"  Item {i+1}: 検証NG - {validated_rule.get('reason')} - Original: {rule_data}")
                     invalid_count += 1
                 else:
                     print(f"  Item {i+1}: 検証OK - {validated_rule}")
                     valid_rules.append(validated_rule)
            print(f"検証結果: 有効 {len(valid_rules)} 件, 無効 {invalid_count} 件")
            # ----------------------------------------

        else:
            print(f"エラー: パース結果がリスト形式ではありません (Type: {type(structured_data_list)})。")
    except json.JSONDecodeError as e:
        print(f"エラー: JSONリスト全体のパースに失敗しました: {e}")
        print(f"対象文字列:\n{cleaned_json_string}")

except Exception as e:
    print(f"エラー: Gemini API呼び出しまたは結果処理中にエラーが発生しました: {e}")

print("\n--- テスト終了 ---") 