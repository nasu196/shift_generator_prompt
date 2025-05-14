# 制約テンプレート実装ステータス

このファイルは、シフト生成モデルで考慮される制約ルールとその実装状況を管理します。

## 個人ルール

### ハード制約・ソフト制約 (is_hardで切り替え可能なルール)

| No. | ルール概要                     | テンプレート案                                                           | AI解釈(JSON) | パーサー検証 | モデル組込 | 備考                                    |
|-----|--------------------------------|--------------------------------------------------------------------------|----------------|--------------|------------|-----------------------------------------|
| 1   | 特定日付シフト指定             | `SPECIFY_DATE_SHIFT(employee, date, shift, is_hard)`                       | ✅           | ✅           | ✅         | `is_hard` でハード/ソフト切替。希望休等に使用。 |
| 2   | 最大連続勤務日数               | `MAX_CONSECUTIVE_WORK(employee, max_days, is_hard)`                      | ✅           | ✅           | ✅         | `is_hard` でハード/ソフト切替。       |
| 3   | 最小/最大 合計シフト数         | `TOTAL_SHIFT_COUNT(employee, shifts, min, max, is_hard)`                 | ✅           | ✅           | ✅         | `is_hard` でハード/ソフト切替。 「正確にN日」はmin/max同値&is_hard:trueで表現。 |
| 4   | 禁止シフト                     | `FORBID_SHIFT(employee, shift)`                                          | ✅           | ✅           | ✅         | (is_hard は常にtrueとして扱われる想定) |
| 5   | 許可シフト限定                 | `ALLOW_ONLY_SHIFTS(employee, allowed_shifts)`                            | ✅           | ✅           | ✅         | (is_hard は常にtrueとして扱われる想定) |
| 6   | 組み合わせNG                   | `FORBID_SIMULTANEOUS_SHIFT(employee1, employee2, shift, is_hard)`        | ✅           | ✅           | ✅         | `is_hard` は現在パーサー/モデルで未反映だが、原則ハード。 |
| 7   | 最大連続公休数                 | `MAX_CONSECUTIVE_OFF(employee, max_days, is_hard)`                       | ✅           | ✅           | ✅         | `is_hard` でハード/ソフト切替。      |
| 8   | 曜日希望/必須                  | `PREFER_WEEKDAY_SHIFT(employee, weekday, shift, weight, is_hard)`        | ✅           | ✅           | ✅         | `is_hard` でハード/ソフト切替。`weight`はSoft時のみ有効。 |
| 9   | シフトシーケンス禁止             | `FORBID_SHIFT_SEQUENCE(employee, preceding_shift, subsequent_shift, is_hard)` | ✅           | ✅           | ✅         | `is_hard` でハード/ソフト切替。      |
| 10  | シフトシーケンス強制             | `ENFORCE_SHIFT_SEQUENCE(employee, preceding_shift, subsequent_shift, is_hard)`| ✅           | ✅           | ✅         | `is_hard` でハード/ソフト切替。例: 夜勤の翌日は必ず明け |

## 施設全体ルール

(AIによるルール解釈・構造化に対応)

### ハード制約・ソフト制約 (is_hardで切り替え可能なルール)

| No. | ルール概要                     | テンプレート案                                                               | AI解釈(JSON) | パーサー検証 | モデル組込 | 備考                                    |
|-----|--------------------------------|--------------------------------------------------------------------------|----------------|--------------|------------|-----------------------------------------|
| F1  | 人員配置基準                   | `REQUIRED_STAFFING(floor, shift, date_type, min_count, is_hard)`           | ✅           | ✅           | ✅         | `is_hard`でハード/ソフト切替。ソフトの場合、不足・超過両方にペナルティ。 |
| F2  | 特定役割の最低出勤             | `MIN_ROLE_ON_DUTY(role, min_count, date_type, is_hard)`                  | ✅           | ✅           | ➖ 未確認  | `is_hard`でハード/ソフト切替。モデル組込は要確認。 |
| F3  | 最大連続公休数 (全体)          | `MAX_CONSECUTIVE_OFF(employee_group, max_days, is_hard)`                 | ✅           | ✅           | ✅         | `is_hard`でハード/ソフト切替。       |
| F4  | 最大連続勤務 (全体)            | `MAX_CONSECUTIVE_WORK(employee_group, max_days, is_hard)`                | ✅           | ✅           | ✅         | `is_hard`でハード/ソフト切替。       |
| F5  | 期間中最低公休数 (グループ別)  | `MIN_TOTAL_SHIFT_DAYS(employee_group, shift, min_count, is_hard)`        | ✅           | ✅           | ✅         | `is_hard`でハード/ソフト切替。 (常勤8日公休など) |
| F6  | シフトシーケンス禁止 (全体)      | `FORBID_SHIFT_SEQUENCE(employee_group, preceding, subsequent, is_hard)`    | ✅           | ✅           | ✅         | `is_hard`でハード/ソフト切替。       |
| F7  | シフトシーケンス強制 (全体)      | `ENFORCE_SHIFT_SEQUENCE(employee_group, preceding, subsequent, is_hard)`   | ✅           | ✅           | ✅         | `is_hard`でハード/ソフト切替。 (夜勤→明→公など) |

### ソフト制約 (常にソフト・weightで調整)

| No. | ルール概要                     | テンプレート案                                                      | AI解釈(JSON) | パーサー検証 | モデル組込 | 備考                                    |
|-----|--------------------------------|-----------------------------------------------------------------|----------------|--------------|------------|-----------------------------------------|
| S1  | 公休日数均等化 (グループ別)    | `BALANCE_OFF_DAYS(employee_group, weight)`                          | ✅           | ✅           | ✅         | 重み調整可能。                          |
| S2  | 特定シフト合計回数均等化       | `BALANCE_SPECIFIC_SHIFT_TOTALS(employee_group, target_shifts, weight, date_type?)` | ✅           | ✅           | ✅         | 重み調整可能。`date_type`はオプショナル。 |

### 対象外 / 代替 / スコープ外 のルール

| No. | ルール概要                     | テンプレート案                                                      | 実装状況 (shift_model.py) | 備考                                    |
|-----|--------------------------------|-----------------------------------------------------------------|---------------------------|-----------------------------------------|
| H2  | 夜勤ローテーション(夜→明, 明→公) | `ENFORCE_NIGHT_ROTATION(employee=\"ALL\")`                          | ✅ (ハードコード)         | ENFORCE_SHIFT_SEQUENCE で代替中。ハードコードも残存。 |
| H_Ext | 応援勤務最小化                 | `MINIMIZE_HELPING(weight)`                                      | ✅ (目的関数)           | (当面は固定ルール)                       |
| S_Ext | 明け人数≒前日夜勤人数         | `BALANCE_AKE_NIGHT_COUNT(weight)`                               | ➖ (現状コメントアウト)   | 開発スコープ外（必要なら後日検討）        |

## パース/モデル未反映・要確認のルール

*   **EMP007, EMP034 の組み合わせNG:** AI解釈(JSON)は前回修正でOKになったが、パーサーログで `employee` と `employee1` に同IDが入っているように見えた件。モデル組込は `employee1`, `employee2` を見てるので問題ないはずだが、AIのJSON出力に不要な `employee` キーが混入していないか確認推奨。 **→最新ログでJSONは正常。パーサーログ表示の問題か、パーサーの一時的な変数名の問題の可能性。モデルへの影響はなしと判断。**
*   **EMP040「日曜日の勤務は2回まで」:**
    *   AI解釈(JSON): `UNPARSABLE` (理由: 曜日と合計回数の組み合わせルール)
    *   パーサー検証: スキップ
    *   モデル組込: 未実装
    *   備考: `MAX_WEEKDAY_SHIFT_COUNT(employee, weekday, shifts, max, is_hard)`のような新ルールタイプが必要。
*   **施設ルール「日勤帯のみ応援勤務がある。」:**
    *   AI解釈(JSON): `UNPARSABLE`
    *   パーサー検証: スキップ
    *   モデル組込: 未実装
    *   備考: 「応援勤務」の概念自体と、それをどう制約に落とし込むかの定義が必要。
*   **施設ルール「希望休が重なった場合には、管理職が出勤して補填を行う」:**
    *   AI解釈(JSON): `UNPARSABLE`
    *   パーサー検証: スキップ
    *   モデル組込: 未実装
    *   備考: 例外的状況への対応であり、現在のルールベースでは表現困難。
*   **施設ルール「祝日に休んでばかりの職員が出ないように配慮する」:**
    *   AI解釈(JSON): `UNPARSABLE`
    *   パーサー検証: スキップ
    *   モデル組込: 未実装
    *   備考: `BALANCE_SPECIFIC_SHIFT_TOTALS` で `date_type=\"HOLIDAY\"`, `shift=\"公\"` として表現できるかAIに再学習させるか、手動でルールファイルに定義する必要あり。

## パース/モデル未反映のルール (CSVより)

*   AMさん: 「基本的に」水曜早出/木曜夜勤 のニュアンス (PREFER_WEEKDAY_SHIFT の weight で表現？)
*   ANさん: 「月に2回程度は日曜勤務可」の頻度/例外ルール (現状のルールタイプでは表現困難) 