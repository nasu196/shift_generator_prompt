# データ読み込み・前処理
import pandas as pd
import re
from datetime import date, timedelta
from src.constants import START_DATE, END_DATE, MANAGER_ROLES, SHIFT_MAP_INT
from src.utils import get_date_range # 年をまたぐ日付パースで使用

def parse_holiday_request(text, year, date_range):
    """希望休文字列をパースして日付オブジェクトのリストを返す"""
    if not isinstance(text, str):
        return [], None

    holidays = []
    status = None
    if '育休中' in text: status = '育休'
    elif '病休中' in text: status = '病休'

    start_date = date_range[0]
    end_date = date_range[-1]

    matches = re.findall(r'(\d{1,2})[/\u6708](\d{1,2})\u65E5?', text)
    for month_str, day_str in matches:
        try:
            month, day = int(month_str), int(day_str)
            current_year_date = date(year, month, day)
            if start_date <= current_year_date <= end_date:
                holidays.append(current_year_date)
            elif start_date.year != end_date.year: # 年越しチェック
                try:
                    next_year_date = date(year + 1, month, day)
                    if start_date <= next_year_date <= end_date:
                         holidays.append(next_year_date)
                except ValueError:
                    pass # 翌年も無効
        except ValueError:
            print(f"警告: 無効な日付形式です - {month_str}/{day_str}")
            continue
    return sorted(list(set(holidays))), status

def parse_constraints(text):
    """シフト作成時の注意点テキストをパースして制約辞書を返す (改善版)"""
    constraints = {}
    if not isinstance(text, str): return constraints

    # --- 連勤制限 (より詳細に) ---
    # Case 1: 「N日以上の〇〇は不可」 (N日目はOK, N+1日目がNG -> 最大N連勤)
    m1 = re.search(r'(\d+)日以上.*?(?:勤務|連勤).*?不可', text)
    if m1:
        try: constraints['max_consecutive_work'] = int(m1.group(1))
        except ValueError: pass
    else:
        # Case 2: 「N連勤は不可」 (N日目がNG -> 最大N-1連勤)
        m2 = re.search(r'(\d+)連勤.*?不可', text)
        if m2:
            try: constraints['max_consecutive_work'] = int(m2.group(1)) - 1
            except ValueError: pass

    # --- 土日祝休み (判定方法変更) ---
    if isinstance(text, str) and \
       ('土' in text or '日曜' in text or '週末' in text) and \
       ('祝' in text or '祭日' in text) and \
       '休' in text:
        constraints['prefer_weekends_off'] = True

    # --- 組み合わせNG (変更なし) ---
    m = re.search(r'([A-Z]+)と同日.*?夜勤.*?避ける', text)
    if m: constraints.setdefault('avoid_night_shift_with', []).append(m.group(1))

    # --- 勤務種別制限 (許可/禁止) ---
    if '日勤・早出のみ' in text:
        constraints['allowed_shifts'] = ['日', '早']
    # elif '夜勤のみ' in text: # 他のパターンがあれば追加
    #     constraints['allowed_shifts'] = ['夜']

    if '夜勤は不可' in text or '夜勤不可' in text:
         constraints.setdefault('disallowed_shifts', []).append('夜')
    # elif '早出は不可' in text: # 他のパターンがあれば追加
    #     constraints.setdefault('disallowed_shifts', []).append('早')

    # --- 曜日希望 (変更なし、無効シフトはフィルタリング済) ---
    weekday_map_jp = {'月': 0, '火': 1, '水': 2, '木': 3, '金': 4, '土': 5, '日': 6}
    shift_map_jp = {'早出': '早', '日勤': '日', '遅番': '遅', '夜勤': '夜', '休み': '公', '公休': '公'}
    for m in re.finditer(r'([月火水木金土日])曜日.*?→?.*?([^\s,、。\uff0c\uff0e]+)', text):
        day_jp, shift_jp = m.groups()
        if day_jp in weekday_map_jp:
            normalized_shift = shift_map_jp.get(shift_jp, shift_jp)
            if normalized_shift in SHIFT_MAP_INT:
                constraints.setdefault('preferred_weekday_shift', {})[weekday_map_jp[day_jp]] = normalized_shift

    # --- 月間勤務日数 (変更なし) ---
    m = re.search(r'(\d+)日勤務', text)
    if m:
        try: constraints['monthly_work_days'] = int(m.group(1))
        except ValueError: pass

    # --- 特定日付希望シフト (変更なし) ---
    date_range_for_parse = get_date_range(START_DATE, END_DATE)
    year = START_DATE.year
    for m in re.finditer(r'(\d{1,2})[/\u6708](\d{1,2})\u65E5?.*?([^\s,、。\uff0c\uff0e]+)希望', text):
        month_str, day_str, shift_jp = m.groups()
        shift_symbol = shift_map_jp.get(shift_jp, shift_jp)
        if shift_symbol not in SHIFT_MAP_INT: continue
        try:
            month, day = int(month_str), int(day_str)
            pref_date = date(year, month, day)
            if date_range_for_parse[0] <= pref_date <= date_range_for_parse[-1]:
                 constraints.setdefault('preferred_date_shift', {})[pref_date] = shift_symbol
            elif date_range_for_parse[0].year != date_range_for_parse[-1].year:
                 try:
                     pref_date_next = date(year + 1, month, day)
                     if date_range_for_parse[0] <= pref_date_next <= date_range_for_parse[-1]:
                        constraints.setdefault('preferred_date_shift', {})[pref_date_next] = shift_symbol
                 except ValueError: pass
        except ValueError: continue

    return constraints

def load_employee_data(filepath):
    """従業員情報をCSVから読み込む"""
    try:
        try: df = pd.read_csv(filepath, encoding="utf-8")
        except UnicodeDecodeError: df = pd.read_csv(filepath, encoding="shift-jis")
        df.columns = df.columns.str.strip()
        floor_col = '担当フロア（1階/2階など）'
        df['担当フロア'] = None
        df['can_help_other_floor'] = False # デフォルトは応援不可
        if floor_col in df.columns:
            for index, row in df.iterrows():
                floor_text = row[floor_col]
                if pd.isna(floor_text): continue

                # 主担当フロア抽出 (1F or 2F)
                match_floor = re.search(r'(1F|2F)', floor_text)
                if match_floor:
                    df.loc[index, '担当フロア'] = match_floor.group(1)
                elif '足りないフロア' in floor_text or row['職員ID'] in ['A', 'B']: # A,Bは特別扱い
                    df.loc[index, '担当フロア'] = '1F' # 仮に1Fを主担当とする
                    df.loc[index, 'can_help_other_floor'] = True # A,Bは応援可

                # 応援可否判定
                if '応援勤務あり' in floor_text or 'どちらでも' in floor_text or df.loc[index, 'can_help_other_floor']: # A,Bは既にTrue
                    df.loc[index, 'can_help_other_floor'] = True

        else: print(f"警告: '{floor_col}' カラムが見つかりません。フロア・応援情報が設定されません。")

        request_col = '希望休（カンマ区切りで日付記入）'
        date_range_for_parse = get_date_range(START_DATE, END_DATE)
        df['parsed_holidays'] = [[] for _ in range(len(df))]
        df['status'] = [None for _ in range(len(df))]
        if request_col in df.columns:
            holidays_status = [parse_holiday_request(req, START_DATE.year, date_range_for_parse) for req in df[request_col]]
            df['parsed_holidays'] = [h[0] for h in holidays_status]
            df['status'] = [h[1] for h in holidays_status]

        constraint_col = 'シフト作成時に気を付けてほしい点'
        df['parsed_constraints'] = [parse_constraints(text) for text in df[constraint_col]] if constraint_col in df.columns else [{} for _ in range(len(df))]

        # --- prefer_weekends_off の再判定 (希望休列も見る) ---
        for index, row in df.iterrows():
            # 既に constraints で True になっている場合は何もしない
            if row['parsed_constraints'].get('prefer_weekends_off'):
                continue
            # 希望休列の内容もチェック
            request_text = row[request_col] if request_col in df.columns and pd.notna(row[request_col]) else ""
            # 判定ロジック (キーワードが含まれるか)
            if ('土' in request_text or '日曜' in request_text or '週末' in request_text) and \
               ('祝' in request_text or '祭日' in request_text) and \
               '休' in request_text:
                 # parsed_constraints 辞書がなければ作成
                 if not isinstance(df.loc[index, 'parsed_constraints'], dict):
                      df.loc[index, 'parsed_constraints'] = {}
                 df.loc[index, 'parsed_constraints']['prefer_weekends_off'] = True

        job_title_col = '常勤/パート'
        df['job_title'] = None
        if job_title_col in df.columns:
             df['job_title'] = df[job_title_col].str.extract(r'\((.*?)\)', expand=False)

        # --- 特定日付希望シフトの再チェック (希望休列も見る) ---
        # parse_constraints 内のロジックを参考に再利用
        shift_map_jp = {'早出': '早', '日勤': '日', '遅番': '遅', '夜勤': '夜', '休み': '公', '公休': '公'}
        year = START_DATE.year
        date_range_for_parse = get_date_range(START_DATE, END_DATE)
        for index, row in df.iterrows():
            request_text = row[request_col] if request_col in df.columns and pd.notna(row[request_col]) else ""
            if not request_text: continue

            for m in re.finditer(r'(\d{1,2})[/\u6708](\d{1,2})\u65E5?.*?([^\s,、。\uff0c\uff0e]+)希望', request_text):
                month_str, day_str, shift_jp = m.groups()
                shift_symbol = shift_map_jp.get(shift_jp, shift_jp)
                if shift_symbol not in SHIFT_MAP_INT: continue
                try:
                    month, day = int(month_str), int(day_str)
                    pref_date = date(year, month, day)
                    if date_range_for_parse[0] <= pref_date <= date_range_for_parse[-1]:
                        # parsed_constraints 辞書と preferred_date_shift がなければ作成
                        if not isinstance(df.loc[index, 'parsed_constraints'], dict):
                             df.loc[index, 'parsed_constraints'] = {}
                        df.loc[index, 'parsed_constraints'].setdefault('preferred_date_shift', {})[pref_date] = shift_symbol
                    elif date_range_for_parse[0].year != date_range_for_parse[-1].year:
                         try:
                             pref_date_next = date(year + 1, month, day)
                             if date_range_for_parse[0] <= pref_date_next <= date_range_for_parse[-1]:
                                  if not isinstance(df.loc[index, 'parsed_constraints'], dict):
                                      df.loc[index, 'parsed_constraints'] = {}
                                  df.loc[index, 'parsed_constraints'].setdefault('preferred_date_shift', {})[pref_date_next] = shift_symbol
                         except ValueError: pass
                except ValueError: continue

        print(f"従業員情報ファイルを読み込み、解析しました (希望休列のシフト希望も考慮): {filepath}")
        # --- DEBUG PRINT: parsed_constraints の内容を出力 (削除) ---
        # print("\n--- Parsed Constraints --- (職員ID: 内容)")
        # for index, row in df.iterrows():
        #     print(f"{row['職員ID']}: {row['parsed_constraints']}")
        # print("--- End Parsed Constraints ---\n")
        # ----------------------------------------------
        return df
    except FileNotFoundError: print(f"エラー: ファイルが見つかりません - {filepath}"); return None
    except Exception as e: print(f"エラー: 従業員情報ファイルの読み込み中にエラー - {e}"); import traceback; traceback.print_exc(); return None

def load_past_shifts(filepath, start_date):
    """直前勤務実績をCSVから読み込む"""
    try:
        try: df = pd.read_csv(filepath, header=None, encoding="utf-8")
        except UnicodeDecodeError: df = pd.read_csv(filepath, header=None, encoding="shift-jis")
        past_date_cols_expected = [(start_date - timedelta(days=i)).strftime('%#m/%#d') for i in range(3, 0, -1)]
        header_row = df.iloc[0, 1:].tolist()
        if len(header_row) >= 3 and header_row[:3] == past_date_cols_expected:
            df.columns = ['職員ID'] + past_date_cols_expected + [f'空列{i+1}' for i in range(len(df.columns) - 4)]
            df = df.iloc[2:].reset_index(drop=True)
            df = df.dropna(axis=1, how='all').dropna(subset=['職員ID'])
            df['職員ID'] = df['職員ID'].astype(str)
            for col in past_date_cols_expected: df[col] = df[col].str.strip()
            print(f"直前勤務実績ファイルを読み込み、整形しました: {filepath}")
            return df[['職員ID'] + past_date_cols_expected]
        else:
            print(f"エラー: 直前勤務実績ファイルのヘッダー形式異常。期待={past_date_cols_expected}, 実際={header_row[:5]}")
            return None
    except FileNotFoundError: print(f"エラー: ファイルが見つかりません - {filepath}"); return None
    except Exception as e: print(f"エラー: 直前勤務実績ファイルの読み込み中にエラー - {e}"); import traceback; traceback.print_exc(); return None 