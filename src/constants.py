# 定数定義
from datetime import date, timedelta

# --- ファイルパス ---
EMPLOYEE_INFO_FILE = "input/employees.csv"
PAST_SHIFT_FILE = "input/past_shifts.csv"
RULES_FILE = "input/rules.csv" # 個人ルール用
FACILITY_RULES_FILE = "input/facility_rules.txt" # 施設ルール用入力ファイル
OUTPUT_DIR = "results"

# --- AI関連 ---
# AI_PROMPT_FILE = "prompts/rule_shaping_prompt.md" # 古い個人ルール用プロンプト (コメントアウト)
PERSONAL_INTERMEDIATE_PROMPT_FILE = "prompts/personal_rule_intermediate_translation_prompt.md" # 個人ルール用 (ステップ1: 中間翻訳)
PERSONAL_STRUCTURED_DATA_PROMPT_FILE = "prompts/rule_shaping_prompt.md" # 個人ルール用 (ステップ2: structured_data生成)
# FACILITY_AI_PROMPT_FILE = "prompts/facility_rule_shaping_prompt.md" # 古い施設ルール用プロンプト (コメントアウト)
FACILITY_INTERMEDIATE_PROMPT_FILE = "prompts/facility_rule_intermediate_translation_prompt.md" # 施設ルール用 (ステップ1: 中間翻訳)
FACILITY_STRUCTURED_DATA_PROMPT_FILE = "prompts/facility_rule_shaping_prompt.md" # 施設ルール用 (ステップ2: structured_data生成)
AI_MODEL_NAME = 'models/gemini-2.5-flash-preview-04-17' # テストに合わせて変更

# --- 期間設定 ---
START_DATE = date(2025, 4, 10)
NUM_WEEKS = 4
END_DATE = START_DATE + timedelta(weeks=NUM_WEEKS) - timedelta(days=1)

# --- シフト関連 ---
# 勤務記号 (基本)
WORK_SYMBOLS = ["日", "公", "夜", "早", "明"]
# 勤務記号と整数IDのマッピング (OR-Tools用)
# 0: 公休, 1: 日勤, 2: 早出, 3: 夜勤, 4: 明け, 5: 育休/病休 (特殊)
SHIFT_MAP_INT = {'公': 0, '日': 1, '早': 2, '夜': 3, '明': 4, '育休': 5, '病休': 5}
SHIFT_MAP_SYM = {v: k for k, v in SHIFT_MAP_INT.items()} # 逆引き用
# 勤務とみなすシフト (連勤計算用)
WORKING_SHIFTS_INT = [SHIFT_MAP_INT[s] for s in ['日', '早', '夜', '明']]
SPECIAL_STATUS_INTS = [SHIFT_MAP_INT['育休']] # 他の休み系記号も追加するなら
OFF_SHIFT_INTS = [SHIFT_MAP_INT['公'], SHIFT_MAP_INT['育休']] # 休み扱い

# --- 人員配置基準 --- (現在は facility_rules.txt から AI が解釈するため不要)
# REQUIRED_PERSONNEL = {
#     "1F": {"早出": 2, "日勤": 4, "夜勤": 2},
#     "2F": {"早出": 3, "日勤": 5, "夜勤": 3}
# }

# --- 制約関連 --- (デフォルト値など)
DEFAULT_MAX_CONSECUTIVE_WORK = 4
MANAGER_MAX_CONSECUTIVE_WORK = 5 # 管理職の連勤上限 (仮)
MANAGER_ROLES = ['主任', '副主任', '班長']

# --- 集計関連 ---
SUMMARY_COLS_SHIFT_SYMBOLS = ["公休", "祝日", "日勤", "早出", "夜勤", "明勤"]
SUMMARY_COLS = [f"集計:{s}" for s in SUMMARY_COLS_SHIFT_SYMBOLS]
DAY_SUMMARY_ROW_NAMES = ["日勤合計", "早出合計", "夜勤合計", "明勤合計"] 