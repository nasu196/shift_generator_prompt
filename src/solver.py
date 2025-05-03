# ソルバー実行
from ortools.sat.python import cp_model

def solve_shift_model(model):
    """CP-SATモデルを解き、ステータスとソルバーオブジェクトを返す"""
    print("Solver started...")
    solver = cp_model.CpSolver()
    # タイムリミットを設定 (例: 60秒)
    # solver.parameters.max_time_in_seconds = 60.0
    # 探索ログを表示する場合
    # solver.parameters.log_search_progress = True
    status = solver.Solve(model)
    print(f"Solver finished with status: {solver.StatusName(status)}")
    return status, solver 