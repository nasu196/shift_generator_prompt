# 制約テンプレート実装ステータス

このファイルは、シフト生成モデルで考慮される制約ルールとその実装状況、およびAIによるルール解釈実験の対象状況を管理します。

## 個人ルール

### ハード制約・ソフト制約 (is_hardで切り替え可能なルール)

| No. | ルール概要                     | テンプレート案                                                           | 実装状況 (shift_model.py) | AI実験対象? | 備考                                    |
|-----|--------------------------------|--------------------------------------------------------------------------|---------------------------|-------------|-----------------------------------------|
| 1   | 特定日付シフト指定             | `SPECIFY_DATE_SHIFT(employee, date, shift, is_hard)`                       | ✅ 実装済み               | ✅ 対象     | `is_hard` でハード/ソフト切替。希望休等に使用。 |
| 4   | 最大連続勤務日数               | `MAX_CONSECUTIVE_WORK(employee, max_days, is_hard)`                      | ✅ 実装済み               | ✅ 対象     | `is_hard` でハード/ソフト切替。       |
| 5   | 最小/最大 合計シフト数         | `TOTAL_SHIFT_COUNT(employee, shifts, min, max, is_hard)`                 | ✅ 実装済み               | ✅ 対象     | `is_hard` でハード/ソフト切替。       |
| 7   | 最大連続公休数                 | `MAX_CONSECUTIVE_OFF(employee, max_days, is_hard)`                       | ✅ 実装済み               | ❌ 対象外   | `is_hard` でハード/ソフト切替。      |
| 8   | 曜日希望/必須                  | `PREFER_WEEKDAY_SHIFT(employee, weekday, shift, weight, is_hard)`        | ✅ 実装済み               | ❌ 対象外   | `is_hard` でハード/ソフト切替。`weight`はSoft時のみ有効。 |
| 9   | シフトシーケンス禁止             | `FORBID_SHIFT_SEQUENCE(employee, preceding_shift, subsequent_shift)`       | ✅ 実装済み               | ❌ 対象外   |                                         |
| 10  | シフトシーケンス強制             | `ENFORCE_SHIFT_SEQUENCE(employee, preceding_shift, subsequent_shift)`      | ✅ 実装済み               | ❌ 対象外   | 例: 夜勤の翌日は必ず明け                  |


## 施設全体ルール

(AIによるルール解釈・構造化に対応)

### ハード制約・ソフト制約 (is_hardで切り替え可能なルール)

| No. | ルール概要                     | テンプレート案                                                               | 実装状況 (shift_model.py) | AI実験対象? | 備考                                    |
|-----|--------------------------------|--------------------------------------------------------------------------|---------------------------|-------------|-----------------------------------------|
| 1   | 人員配置基準（フロア別＆合計） | `REQUIRED_STAFFING(floor, shift, date_type, min_count, is_hard)`           | ✅ 実装済み               | ✅ 対象     | `is_hard` でハード/ソフト切替。       |
| 3   | 特定役割の最低出勤             | `MIN_ROLE_ON_DUTY(role, min_count, date_type, is_hard)`              | ✅ 実装済み               | ✅ 対象     | `is_hard` でハード/ソフト切替。       |
| 4   | 最大連続公休数 (全体)          | `MAX_CONSECUTIVE_OFF(employee_group="ALL", max_days, is_hard)`         | ✅ 実装済み               | ✅ 対象     | `is_hard` でハード/ソフト切替。       |
| 5   | シフトシーケンス禁止 (全体)      | `FORBID_SHIFT_SEQUENCE(employee_group="ALL", preceding, subsequent, is_hard)` | ✅ 実装済み               | ✅ 対象     | `is_hard` でハード/ソフト切替。       |
| 6   | シフトシーケンス強制 (全体)      | `ENFORCE_SHIFT_SEQUENCE(employee_group="ALL", preceding, subsequent, is_hard)`| ✅ 実装済み               | ✅ 対象     | `is_hard` でハード/ソフト切替。       |

### ソフト制約 (常にソフト・weightで調整)

| No. | ルール概要              | テンプレート案                               | 実装状況 (shift_model.py) | AI実験対象? | 備考                                    |
|-----|-------------------------|----------------------------------------------|---------------------------|-------------|-----------------------------------------|
| 1   | 公休日数均等化          | `BALANCE_OFF_DAYS(employee_group, weight)`   | ✅ 実装済み               | ✅ 対象     | 重み調整可能。                          |

### 対象外 / 代替 / スコープ外 のルール

| No. | ルール概要                     | テンプレート案                                                      | 実装状況 (shift_model.py) | AI実験対象? | 備考                                    |
|-----|--------------------------------|-----------------------------------------------------------------|---------------------------|-------------|-----------------------------------------|
| H2  | 夜勤ローテーション(夜→明, 明→公) | `ENFORCE_NIGHT_ROTATION(employee="ALL")`                          | ✅ 実装済み (制約#5)      | ❌ 対象外   | ENFORCE_SHIFT_SEQUENCE で代替可。必要ならハードコード実行。 |
| S2  | 応援勤務最小化                 | `MINIMIZE_HELPING(weight)`                                      | ✅ 実装済み (目的関数内)  | ❌ 対象外   | (当面は固定ルール)                       |
| S3  | 明け人数≒前日夜勤人数         | `BALANCE_AKE_NIGHT_COUNT(weight)`                               | ✅ 実装済み (制約#5b)     | ❌ 対象外   | 開発スコープ外（必要なら後日検討）        |


## パース/モデル未反映のルール (CSVより)

*   AMさん: 「基本的に」水曜早出/木曜夜勤 のニュアンス (PREFER_WEEKDAY_SHIFT の weight で表現？)
*   ANさん: 「月に2回程度は日曜勤務可」の頻度/例外ルール (現状のルールタイプでは表現困難) 