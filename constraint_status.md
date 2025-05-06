# 制約テンプレート実装ステータス

このファイルは、シフト生成モデルで考慮される制約ルールとその実装状況、およびAIによるルール解釈実験の対象状況を管理します。

## 個人ルール

### ハード制約 (必ず守る)

| No. | ルール概要                     | テンプレート案                                                           | 実装状況 (shift_model.py) | AI実験対象? | 備考                                    |
|-----|--------------------------------|--------------------------------------------------------------------------|---------------------------|-------------|-----------------------------------------|
| 1   | 特定日付シフト指定             | `SPECIFY_DATE_SHIFT(employee, date, shift, is_hard)`                       | ✅ 一部実装済み (旧ASSIGN流用) | ✅ 対象     | `is_hard` が `true` ならハード、`false` ならソフト。希望休/病休/育休/祝日休み指定にも使用。 |
| 2   | 禁止シフト                     | `FORBID_SHIFT(employee, shift)`                                          | ✅ 実装済み (制約#7内)      | ✅ 対象     | 「夜勤はできません」                      |
| 3   | 許可シフト限定                 | `ALLOW_ONLY_SHIFTS(employee, allowed_shifts)`                            | ✅ 実装済み (制約#10)     | ✅ 対象     | 「日勤と早出のみ可能」                  |
| 4   | 最大連続勤務日数               | `MAX_CONSECUTIVE_WORK(employee, max_days, is_hard)`                      | ✅ 実装済み              | ✅ 対象     | `is_hard` でハード/ソフトを切り替え。 |
| 5   | 最小/最大 合計シフト数         | `TOTAL_SHIFT_COUNT(employee, shifts, min, max, is_hard)`                 | ✅ 実装済み              | ✅ 対象     | `is_hard` でハード/ソフト切替。       |
| 6   | 組み合わせNG                   | `FORBID_SIMULTANEOUS_SHIFT(employee1, employee2, shift)`                 | ✅ 実装済み (制約#9)      | ✅ 対象     | 「EMP004さんと同じ日の夜勤はNG」        |
| 7   | 最大連続公休数                 | `MAX_CONSECUTIVE_OFF(employee, max_days, is_hard)`                       | ✅ 実装済み              | ❌ 対象外   | `is_hard` でハード/ソフトを切り替え。      |
| 9   | シフトシーケンス禁止             | `FORBID_SHIFT_SEQUENCE(employee, preceding_shift, subsequent_shift)`       | ✅ 実装済み               | ❌ 対象外   |                                         |
| 10  | シフトシーケンス強制             | `ENFORCE_SHIFT_SEQUENCE(employee, preceding_shift, subsequent_shift)`      | ✅ 実装済み               | ❌ 対象外   | 例: 夜勤の翌日は必ず明け                  |

### ソフト制約 (できるだけ守る)

| No. | ルール概要                     | テンプレート案                                                           | 実装状況 (shift_model.py) | AI実験対象? | 備考                                    |
|-----|--------------------------------|--------------------------------------------------------------------------|---------------------------|-------------|-----------------------------------------|
| 1   | 曜日希望                       | `PREFER_WEEKDAY_SHIFT(employee, weekday, shift, weight, is_hard)`        | ⏳ 一部実装(Softのみ)   | ❌ 対象外   | `is_hard`でハード/ソフト切替。例:「日曜は絶対休み」 |

## 施設全体ルール

(施設全体ルールは、現在の実験スコープではAIによる解釈対象外とし、OR-Toolsモデルに直接組み込む想定)

### ハード制約 (必ず守る)

| No. | ルール概要                     | テンプレート案                                                      | 実装状況 (shift_model.py) | AI実験対象? | 備考                                    |
|-----|--------------------------------|-----------------------------------------------------------------|---------------------------|-------------|-----------------------------------------|
| 1   | 人員配置基準（フロア別＆合計） | `REQUIRED_STAFFING(floor, shift, date_type, min_count, is_hard)` | ❌ 未実装                 | ✅ 対象     | is_hard=true 想定だがパラメータ化する   |
| 2   | 夜勤ローテーション(夜→明, 明→公) | `ENFORCE_NIGHT_ROTATION(employee="ALL")`                          | ✅ 実装済み (制約#5)      | ❌ 対象外   | ENFORCE_SHIFT_SEQUENCE で代替するため専用ルール不要 |
| 3   | 特定役割の最低出勤             | `MIN_ROLE_ON_DUTY(role, min_count, date_type, is_hard)`         | ❌ 未実装                 | ✅ 対象     | is_hard=true 想定だがパラメータ化する   |
| 4   | 最大連続公休数 (全体)          | `MAX_CONSECUTIVE_OFF(employee_group="ALL", max_days, is_hard)` | ❌ 未実装                 | ✅ 対象     | 個人ルールと統合 or 専用タイプを検討    |
| 5   | シフトシーケンス禁止 (全体)      | `FORBID_SHIFT_SEQUENCE(employee="ALL", preceding, subsequent)`    | ❌ 未実装                 | ❌ 対象外   |                                         |

### ソフト制約 (できるだけ守る)

| No. | ルール概要              | テンプレート案                               | 実装状況 (shift_model.py) | AI実験対象? | 備考                                    |
|-----|-------------------------|----------------------------------------------|---------------------------|-------------|-----------------------------------------|
| 1   | 公休日数均等化          | `BALANCE_OFF_DAYS(employee_group, weight)`   | ❌ 未実装                 | ✅ 対象     | is_hard=false 想定。重み調整。         |
| 2   | 応援勤務最小化          | `MINIMIZE_HELPING(weight)`                   | ✅ 実装済み (目的関数内)  | ❌ 対象外   | (固定ルール)                            |
| 3   | 明け人数≒前日夜勤人数  | `BALANCE_AKE_NIGHT_COUNT(weight)`            | ✅ 実装済み (制約#5b)     | ❌ 対象外   | 開発スコープ外（必要なら後日検討）        |
| 4   | シフトシーケンス強制 (全体) | `PREFER_SHIFT_SEQUENCE(employee="ALL", ...)` | ❌ 未実装                 | ❌ 対象外   |                                         |

## パース/モデル未反映のルール (CSVより)

*   AMさん: 「基本的に」水曜早出/木曜夜勤 のニュアンス
*   ANさん: 「月に2回程度は日曜勤務可」の頻度/例外ルール 