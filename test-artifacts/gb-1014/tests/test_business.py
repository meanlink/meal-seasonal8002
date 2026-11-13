"""按周滚动回测业务口径的独立单元测试（仅依赖 Python 标准库）。

运行：python3 test_business.py
覆盖：
1. 滚动折的训练截止日逐周推进，且每折预测不读取验证日之后的数据；
2. 汇总 MAE/WAPE 由各周分子分母加总得到，不等于各周百分比的平均；
3. 缓冲只改变建议备餐量，不改变回测指标与基础预测；
4. 校验失败态（不足49天、不连续、混合档口、负份数、零实领、参数越界）；
5. 结果快照绑定所用记录指纹，记录更新后旧结果仍可复现。
"""
import math
import os
import sys
import unittest
from datetime import date, timedelta

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend"))
sys.path.insert(0, BACKEND)

from src.services import business  # noqa: E402


def _records(n=112, start=date(2026, 7, 20), shift=0.0):
    weekday = [480, 520, 550, 530, 470, 180, 140]
    rows = []
    for i in range(n):
        day = start + timedelta(days=i)
        rows.append({
            "date": day.isoformat(),
            "demand": weekday[day.weekday()] + 0.45 * i + shift,
            "meal": "东港园午餐",
        })
    return rows


class RollingBacktestTests(unittest.TestCase):
    def setUp(self):
        self.params = {"alpha": 0.35, "horizon": 7, "safety_pct": 8}
        self.records = business.seed_records()
        self.result = business.analyze(self.records, self.params)

    def test_fold_count_and_cutoff_progression(self):
        bt = self.result["backtest"]
        # 112天：cut 从14起、每次+7，最后 cut+7<=112 → cut=14..105，共14折。
        self.assertEqual(bt["aggregate"]["folds"], 14)
        self.assertEqual(bt["aggregate"]["days"], 14 * 7)
        cutoffs = [f["train_cutoff"] for f in bt["folds"]]
        self.assertEqual(cutoffs[0], date(2026, 8, 2).isoformat())  # 第14天
        d0 = date.fromisoformat(cutoffs[0])
        for i, c in enumerate(cutoffs):
            self.assertEqual(date.fromisoformat(c), d0 + timedelta(days=7 * i))
        # 每折训练天数随截止日推进。
        self.assertEqual([f["train_days"] for f in bt["folds"]], [14 + 7 * i for i in range(14)])
        # 预测窗口紧随截止日之后，且止于数据末日。
        self.assertEqual(bt["folds"][-1]["window_end"], self.records[-1]["date"])

    def test_no_future_data_leakage(self):
        """手动重算任一折：只用截止日前记录，结果必须与存储折完全一致。"""
        parsed = sorted((date.fromisoformat(r["date"]), float(r["demand"])) for r in self.records)
        values = [v for _, v in parsed]
        dates = [d for d, _ in parsed]
        for fold in self.result["backtest"]["folds"]:
            cut = fold["train_days"]
            pred = business._forecast(values[:cut], 7, self.params["alpha"])
            naive = values[cut - 7:cut]
            for j, day_row in enumerate(fold["days"]):
                self.assertEqual(day_row["date"], dates[cut + j].isoformat())
                self.assertAlmostEqual(day_row["forecast"], round(pred[j], 1), places=6)
                self.assertAlmostEqual(day_row["naive"], round(naive[j], 1), places=6)
                self.assertAlmostEqual(day_row["actual"], round(values[cut + j], 1), places=6)

    def test_aggregate_uses_pooled_errors_not_average_of_percentages(self):
        agg = self.result["backtest"]["aggregate"]
        folds = self.result["backtest"]["folds"]
        pooled_abs = sum(f["abs_error_sum"] for f in folds)
        pooled_naive = sum(f["naive_abs_error_sum"] for f in folds)
        pooled_actual = sum(f["actual_sum"] for f in folds)
        self.assertAlmostEqual(agg["abs_error_sum"], round(pooled_abs, 1), places=6)
        self.assertAlmostEqual(agg["actual_sum"], round(pooled_actual, 1), places=6)
        self.assertAlmostEqual(agg["mae"], round(pooled_abs / agg["days"], 2), places=6)
        self.assertAlmostEqual(agg["wape"], round(pooled_abs / pooled_actual * 100, 2), places=6)
        self.assertAlmostEqual(agg["naive_wape"], round(pooled_naive / pooled_actual * 100, 2), places=6)
        # 显式断言：汇总 WAPE 不等于“各周WAPE的算术平均”（用未舍入表达式比较）。
        per_fold_wape = [100 * f["abs_error_sum"] / f["actual_sum"] for f in folds]
        pooled_wape_raw = 100 * pooled_abs / pooled_actual
        self.assertNotAlmostEqual(pooled_wape_raw, sum(per_fold_wape) / len(folds), places=6)
        self.assertIn("不平均各周百分比", agg["rule"])

    def test_daily_reconciliation_math(self):
        for fold in self.result["backtest"]["folds"]:
            for day in fold["days"]:
                self.assertAlmostEqual(day["diff"], round(day["forecast"] - day["actual"], 1), places=6)
                self.assertAlmostEqual(day["naive_diff"], round(day["naive"] - day["actual"], 1), places=6)
                self.assertAlmostEqual(day["abs_error"], abs(day["diff"]), places=6)
            self.assertAlmostEqual(
                fold["mae"], round(sum(d["abs_error"] for d in fold["days"]) / 7, 2), delta=0.05)

    def test_buffer_only_changes_plans(self):
        r8 = business.analyze(self.records, {**self.params, "safety_pct": 8})
        r20 = business.analyze(self.records, {**self.params, "safety_pct": 20})
        r0 = business.analyze(self.records, {**self.params, "safety_pct": 0})
        # 回测与基础预测完全不受缓冲影响。
        self.assertEqual(r8["backtest"], r20["backtest"])
        self.assertEqual([row["forecast"] for row in r8["table"]["rows"]],
                         [row["forecast"] for row in r20["table"]["rows"]])
        plans8 = [row["plan"] for row in r8["table"]["rows"]]
        plans20 = [row["plan"] for row in r20["table"]["rows"]]
        plans0 = [row["plan"] for row in r0["table"]["rows"]]
        self.assertTrue(all(p20 >= p8 >= p0 for p20, p8, p0 in zip(plans20, plans8, plans0)))
        full_values = [float(r["demand"]) for r in self.records]
        for base, row in zip(business._forecast(full_values, 7, 0.35), r20["table"]["rows"]):
            self.assertEqual(row["plan"], math.ceil(base * 1.20 - 1e-9))
            self.assertAlmostEqual(row["buffer"], round(row["plan"] - base, 1), places=6)

    def test_snapshot_fingerprint_and_immutability(self):
        snap = self.result["snapshot"]
        self.assertEqual(snap["record_count"], 112)
        self.assertEqual(snap["date_start"], self.records[0]["date"])
        self.assertEqual(snap["date_end"], self.records[-1]["date"])
        self.assertEqual(snap["checksum"], business._records_fingerprint(self.records))
        # 源数据“更新”（追加7天）后重算，旧结果指纹仍指向旧记录、结果不变。
        old_checksum = snap["checksum"]
        updated = self.records + _records(7, date.fromisoformat(self.records[-1]["date"]) + timedelta(days=1))
        new_result = business.analyze(updated, self.params)
        self.assertEqual(self.result["snapshot"]["checksum"], old_checksum)
        self.assertNotEqual(new_result["snapshot"]["checksum"], old_checksum)
        self.assertEqual(new_result["backtest"]["aggregate"]["folds"], 15)

    def test_validation_failures(self):
        cases = [
            ("不足49天", _records(48)),
            ("日期不连续", self.records[:50] + self.records[52:]),
            ("混合档口", [{**r, "meal": "西餐档"} if i == 10 else r for i, r in enumerate(self.records)]),
            ("负份数", [{**r, "demand": -1} if i == 5 else r for i, r in enumerate(self.records)]),
        ]
        for label, rows in cases:
            with self.assertRaises(ValueError, msg=label):
                business.analyze(rows, self.params)
        bad_params = [
            {"alpha": 0.05, "horizon": 7, "safety_pct": 8},
            {"alpha": 0.35, "horizon": 7.5, "safety_pct": 8},
            {"alpha": 0.35, "horizon": 5, "safety_pct": 8},
            {"alpha": 0.35, "horizon": 7, "safety_pct": 25},
        ]
        for p in bad_params:
            with self.assertRaises(ValueError):
                business.analyze(self.records, p)

    def test_all_zero_actual_rejected(self):
        rows = _records(49)
        # 所有回测日（第15天起）实领为0，WAPE 分母为0，必须拒绝。
        for r in rows[14:]:
            r["demand"] = 0
        with self.assertRaises(ValueError):
            business.analyze(rows, self.params)

    def test_49_days_produces_five_weekly_folds(self):
        rows = _records(49)
        result = business.analyze(rows, self.params)
        # cut=14,21,28,35,42 → 5 个完整7天折。
        self.assertEqual(result["backtest"]["aggregate"]["folds"], 5)
        self.assertEqual(result["backtest"]["folds"][0]["train_days"], 14)
        self.assertEqual(result["backtest"]["folds"][-1]["train_days"], 42)

    def test_seed_is_deterministic(self):
        self.assertEqual(business.seed_records(), business.seed_records())
        self.assertEqual(len(business.seed_records()), 112)

    def test_future_forecast_uses_full_history(self):
        rows = self.result["table"]["rows"]
        self.assertEqual(len(rows), 7)
        first_future = date.fromisoformat(self.records[-1]["date"]) + timedelta(days=1)
        self.assertEqual(rows[0]["date"], first_future.isoformat())
        self.assertTrue(all(r["plan"] >= 0 for r in rows))
        # 非负截断：构造全零尾部数据，预测不得为负。
        zero_rows = [{**r, "demand": 0} for r in _records(60)[-14:]]
        base_rows = _records(60)[:-14] + zero_rows
        result = business.analyze(base_rows, self.params)
        self.assertTrue(all(r["forecast"] >= 0 for r in result["table"]["rows"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
