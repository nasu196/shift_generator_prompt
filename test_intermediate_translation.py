import google.generativeai as genai
import os
from dotenv import load_dotenv # dotenvライブラリをインポート

# .envファイルから環境変数を読み込む
# この行が実行されると、.envファイル内のキー=値が環境変数として設定される
load_dotenv()

# --- 設定項目 ---
API_KEY = os.environ.get("GEMINI_API_KEY") # 環境変数からAPIキーを取得 (dotenv経由で読み込まれるはず)
TARGET_YEAR = 2025 # テスト用の年

FACILITY_RULES_FILE = "input/facility_rules.txt"
INTERMEDIATE_PROMPT_FILE = "prompts/facility_rule_intermediate_translation_prompt.md"

# --- Gemini APIクライアントの設定 ---
if not API_KEY:
    print("エラー: 環境変数 GEMINI_API_KEY が設定されていません。(.envファイルを確認してください)") # エラーメッセージを少し変更
    exit()
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash') # モデル名を変更

# --- ファイル読み込み ---
try:
    with open(FACILITY_RULES_FILE, 'r', encoding='utf-8') as f:
        facility_rules_text = f.read()
    print(f"--- 入力施設ルール ({FACILITY_RULES_FILE}) ---")
    print(facility_rules_text)
except FileNotFoundError:
    print(f"エラー: {FACILITY_RULES_FILE} が見つかりません。")
    exit()

try:
    with open(INTERMEDIATE_PROMPT_FILE, 'r', encoding='utf-8') as f:
        prompt_template = f.read()
except FileNotFoundError:
    print(f"エラー: {INTERMEDIATE_PROMPT_FILE} が見つかりません。")
    exit()

# --- プロンプトの構築 ---
# {facility_rules_text} と {target_year} をプロンプトに埋め込む
# プロンプト内の他の { や } はエスケープされている前提
final_prompt = prompt_template.format(
    facility_rules_text=facility_rules_text,
    target_year=TARGET_YEAR
)
# print("\n--- 生成されたプロンプト (Gemini APIへ送信) ---")
# print(final_prompt) # デバッグ用にプロンプト全体を表示したい場合

# --- Gemini API呼び出し ---
print(f"\n--- Gemini API呼び出し中 (中間翻訳ステップ) ---")
try:
    response = model.generate_content(final_prompt)
    intermediate_translation = response.text
    print("\n--- AIによる中間翻訳結果 ---")
    print(intermediate_translation)
except Exception as e:
    print(f"エラー: Gemini API呼び出し中にエラーが発生しました: {e}")
    # エラーレスポンスの詳細を表示したい場合
    # if hasattr(e, 'response') and e.response:
    #     print("API Response:", e.response)

print("\n--- テスト終了 ---") 