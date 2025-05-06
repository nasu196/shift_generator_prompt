import google.generativeai as genai
import os
import pandas as pd
import json
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む (ない場合は手動で設定)
load_dotenv()

# APIキーを設定 (環境変数 GEMINI_API_KEY を設定してください)
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("エラー: 環境変数 'GEMINI_API_KEY' が設定されていません。")
    exit()

genai.configure(api_key=api_key)

# --- 入力データの準備 ---
RULES_CSV_PATH = "input/rules.csv"
PROMPT_FILE_PATH = "prompts/rule_shaping_prompt.md"

def load_rules_csv(file_path: str) -> pd.DataFrame | None:
    """ルールCSVファイルを読み込む"""
    try:
        df = pd.read_csv(file_path, dtype=str).fillna('') # NaNを空文字に
        print(f"--- {file_path} の内容 ---")
        print(df.to_string())
        print("-" * 20)
        return df
    except FileNotFoundError:
        print(f"エラー: ファイルが見つかりません: {file_path}")
        return None
    except Exception as e:
        print(f"エラー: {file_path} の読み込み中にエラーが発生しました: {e}")
        return None

def load_prompt(file_path: str) -> str | None:
    """プロンプトファイルを読み込み、フォーマット用に中括弧をエスケープする"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            prompt_raw = f.read()

        # プレースホルダーを一時的に退避させるためのユニークな文字列
        placeholder = "{input_csv_data}"
        temp_placeholder = "___INPUT_CSV_DATA_PLACEHOLDER___"

        if placeholder not in prompt_raw:
            print(f"警告: プロンプトファイルにプレースホルダー '{placeholder}' が見つかりません。そのままエスケープ処理を行います。")
            # プレースホルダーがない場合は、単純に全ての中括弧をエスケープ
            prompt_processed = prompt_raw.replace('{', '{{').replace('}', '}}')
        else:
            # 1. プレースホルダーを一時的な文字列に置換
            prompt_temp = prompt_raw.replace(placeholder, temp_placeholder)
            # 2. 残りのすべての中括弧をエスケープ
            prompt_escaped = prompt_temp.replace('{', '{{').replace('}', '}}')
            # 3. 一時的な文字列を元のプレースホルダーに戻す (これで format 可能になる)
            prompt_processed = prompt_escaped.replace(temp_placeholder, placeholder)

        print(f"--- {file_path} の内容 (先頭部分) ---")
        print(prompt_processed[:500] + "...") # エスケープ処理後のものを表示
        print("-" * 20)
        return prompt_processed # エスケープ処理後のプロンプト文字列を返す

    except FileNotFoundError:
        print(f"エラー: ファイルが見つかりません: {file_path}")
        return None
    except Exception as e:
        print(f"エラー: {file_path} の読み込みまたはエスケープ処理中にエラーが発生しました: {e}")
        return None

def format_input_for_prompt(rules_df: pd.DataFrame) -> str:
    """DataFrameをプロンプト用のCSV形式文字列に変換"""
    # ヘッダー行を含める
    lines = ["職員ID,ルール・希望 (自然言語)"]
    # 各行をフォーマットして追加
    for _, row in rules_df.iterrows():
        # ルール内のダブルクォートをエスケープ
        rule_text = str(row['ルール・希望 (自然言語)']).replace('"', '""')
        # CSV行を作成し、ルールをダブルクォートで囲む
        lines.append(f"{row['職員ID']},\"{rule_text}\"")

    return "\n".join(lines) # 各行をLFで結合

# --- メイン処理 ---
if __name__ == "__main__":
    rules_df = load_rules_csv(RULES_CSV_PATH)
    # load_prompt はエスケープ処理済みのテンプレート文字列を返す
    base_prompt_template = load_prompt(PROMPT_FILE_PATH)

    if rules_df is None or base_prompt_template is None:
        print("エラー: 入力ファイルまたはプロンプトファイルの読み込み/処理に失敗しました。")
        exit()

    # プロンプトに入力データを組み込む
    input_rules_text = format_input_for_prompt(rules_df)

    # f-string ではなく .format() を使用してプレースホルダーにデータを挿入
    try:
        final_prompt = base_prompt_template.format(input_csv_data=input_rules_text)
        print("--- 組み立てられた最終プロンプト (一部) ---")
        print(final_prompt[:800] + "...")
        print("-" * 20)
    except KeyError as e: # より具体的なエラーを捕捉
        print(f"エラー: プロンプトテンプレートのフォーマット中にキーエラーが発生しました: {e}")
        print(f"'{e}' という名前のプレースホルダーが見つかりません。プロンプトとコードを確認してください。")
        final_prompt = None
    except Exception as e:
        print(f"エラー: プロンプトのフォーマット中に予期せぬエラーが発生しました: {e}")
        final_prompt = None

    # Gemini API呼び出しを実行
    if final_prompt:
        print("\nGemini API を呼び出します...")
        # モデルを選択 (Flash-Liteモデルを試す)
        model = genai.GenerativeModel('gemini-2.0-flash-lite')
        try:
            # Safety settingsを調整 (必要に応じて)
            # safety_settings = [
            #     {
            #         "category": "HARM_CATEGORY_HARASSMENT",
            #         "threshold": "BLOCK_NONE",
            #     },
            #     # 他のカテゴリも同様に設定可能
            # ]

            # GenerationConfig を使用して JSON モードを試みる (モデルが対応していれば)
            # try:
            #     response = model.generate_content(
            #         final_prompt,
            #         generation_config=genai.types.GenerationConfig(
            #             response_mime_type="application/json"
            #         ),
            #         # safety_settings=safety_settings
            #     )
            #     response_text = response.text
            # except Exception as json_mode_err:
            #     print(f"情報: JSONモードでの生成に失敗しました ({json_mode_err})。通常のテキストモードで再試行します。")
            #     response = model.generate_content(final_prompt) # , safety_settings=safety_settings)
            #     response_text = response.text

            # シンプルなテキスト生成で開始
            response = model.generate_content(final_prompt)
            response_text = response.text

            print("\n--- API応答 (未加工) ---")
            print(response_text)

            # 応答テキストからJSON部分を抽出・パース
            print("\n--- 抽出されたJSON ---")
            try:
                # ```json ``` マークダウンブロックを探す
                json_block_start = response_text.find("```json")
                json_block_end = response_text.rfind("```")

                if json_block_start != -1 and json_block_end != -1 and json_block_start < json_block_end:
                    # ```json\n と ``` を除いた部分を抽出
                    json_string = response_text[json_block_start + 7 : json_block_end].strip()
                    parsed_json = json.loads(json_string)
                    print(json.dumps(parsed_json, indent=2, ensure_ascii=False))
                else:
                    # マークダウンブロックが見つからない場合、全体をパース試行
                    print("警告: ```json ブロックが見つかりませんでした。応答全体をJSONとしてパース試行します。")
                    parsed_json = json.loads(response_text)
                    print(json.dumps(parsed_json, indent=2, ensure_ascii=False))

            except json.JSONDecodeError as e:
                print(f"JSONのパースに失敗しました: {e}")
                print("応答テキスト全体を確認してください。")
            except Exception as e:
                print(f"JSON処理中に予期せぬエラーが発生しました: {e}")

        except Exception as e:
            print(f"エラー: Gemini API呼び出しまたは結果処理中にエラーが発生しました: {e}")
        pass # API呼び出しは次のステップで 