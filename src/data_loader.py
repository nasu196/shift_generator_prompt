# データ読み込み・前処理
import pandas as pd
import re
from datetime import date, timedelta
# constants から新しいファイルパス定数をインポート
from src.constants import (
    START_DATE, END_DATE, # load_past_shifts で使用
    EMPLOYEE_INFO_FILE, PAST_SHIFT_FILE, RULES_FILE # 各ロード関数で使用
)
# from src.utils import get_date_range # load_employee_data内では使わなくなった
# from src.constants import SHIFT_MAP_INT # parse_constraints削除により不要

def load_employee_data(filepath=EMPLOYEE_INFO_FILE):
    """従業員基本情報CSVを読み込む"""
    try:
        try: df = pd.read_csv(filepath, encoding="utf-8")
        except UnicodeDecodeError: df = pd.read_csv(filepath, encoding="shift-jis")
        df.columns = df.columns.str.strip()

        # 基本的な情報（担当フロア、役職など）を抽出・整理
        # 担当フロア (列が存在すれば)
        if '担当フロア' in df.columns:
            # 必要ならここで 1F/2F 以外の値を None にするなどの処理
            pass # 今回は特に処理不要か
        else:
            print(f"警告: {filepath} に '担当フロア' 列がありません。")
            df['担当フロア'] = None # 列自体を作成

        # 役職 (列が存在すれば)
        if '役職' not in df.columns:
             print(f"警告: {filepath} に '役職' 列がありません。")
             df['役職'] = None

        # 常勤/パート (列が存在すれば)
        if '常勤/パート' not in df.columns:
             print(f"警告: {filepath} に '常勤/パート' 列がありません。")
             df['常勤/パート'] = None

        # 応援可否列は削除されたので、関連処理は不要

        # ルールパース関連の処理はここから削除
        # df['parsed_holidays'] = ...
        # df['status'] = ...
        # df['parsed_constraints'] = ...
        # df['job_title'] = ...

        print(f"従業員基本情報を読み込みました: {filepath}")
        # 必要な基本情報カラムのみを返すようにしても良い
        # return df[['職員ID', '職員名', '担当フロア', '役職', '常勤/パート']]
        return df
    except FileNotFoundError: print(f"エラー: ファイルが見つかりません - {filepath}"); return None
    except Exception as e: print(f"エラー: 従業員情報の読み込み中にエラー - {e}"); import traceback; traceback.print_exc(); return None

def load_past_shifts(filepath=PAST_SHIFT_FILE, start_date=START_DATE):
    """直前勤務実績をCSVから読み込む"""
    try:
        # ヘッダーが日付(4/7形式)であることを期待
        try: df = pd.read_csv(filepath, encoding="utf-8")
        except UnicodeDecodeError: df = pd.read_csv(filepath, encoding="shift-jis")

        df.columns = df.columns.str.strip()
        required_cols = ['職員ID'] + [(start_date - timedelta(days=i)).strftime('%#m/%#d') for i in range(3, 0, -1)]

        # 必要なカラムが存在するかチェック
        if not all(col in df.columns for col in required_cols):
            print(f"エラー: 直前勤務実績ファイルに必要なカラムが不足しています。期待: {required_cols}, 実際: {df.columns.tolist()}")
            return None

        # 職員IDを文字列に変換
        df['職員ID'] = df['職員ID'].astype(str)
        # シフト記号の空白を除去
        for col in required_cols[1:]: # 日付カラムのみ
             df[col] = df[col].astype(str).str.strip()

        print(f"直前勤務実績ファイルを読み込みました: {filepath}")
        return df[required_cols] # 必要な列だけ返す

    except FileNotFoundError: print(f"エラー: ファイルが見つかりません - {filepath}"); return None
    except Exception as e: print(f"エラー: 直前勤務実績ファイルの読み込み中にエラー - {e}"); import traceback; traceback.print_exc(); return None

def load_natural_language_rules(filepath=RULES_FILE):
    """自然言語ルールCSVを読み込み、{職員ID: ルール文字列} の辞書を返す"""
    try:
        try: df = pd.read_csv(filepath, encoding="utf-8")
        except UnicodeDecodeError: df = pd.read_csv(filepath, encoding="shift-jis")
        df.columns = df.columns.str.strip()

        if '職員ID' not in df.columns or 'ルール・希望 (自然言語)' not in df.columns:
             print(f"エラー: ルールファイルに必要なカラム（職員ID, ルール・希望 (自然言語)）がありません: {filepath}")
             return {}

        rules_dict = {}
        for _, row in df.iterrows():
            emp_id = str(row['職員ID']).strip()
            rule_text = row['ルール・希望 (自然言語)']
            # NaNや空文字列は空のルールとして扱う
            rules_dict[emp_id] = str(rule_text).strip() if pd.notna(rule_text) else ""

        print(f"自然言語ルールファイルを読み込みました: {filepath}")
        return rules_dict
    except FileNotFoundError: print(f"エラー: ファイルが見つかりません - {filepath}"); return {}
    except Exception as e: print(f"エラー: 自然言語ルールファイルの読み込み中にエラー - {e}"); return {}

# --- ここから下は古いパース関数なので削除 --- #
# def parse_holiday_request(...):
#     ...
# def parse_constraints(...):
#     ... 