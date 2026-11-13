"""星期周期的加法Holt-Winters预测、按周滚动回测与备餐缓冲。

回测口径（滚动周留出）：
- 以7天为一折，训练截止日逐周向后推进；每折仅使用截止日（含）之前的
  领餐记录拟合模型，预测随后7天，绝不读取验证日及之后的任何数据。
- 每折同时给出“上周同日”季节朴素基线（训练窗口最后7天循环），与HW逐日对账。
- 汇总误差在各周误差的分子/分母层面加总后计算，不平均各周百分比：
  MAE = 全部对账日绝对误差之和 / 对账天数；
  WAPE = 全部对账日绝对误差之和 / 全部对账日实际之和 ×100%。
"""
from datetime import date, timedelta
import hashlib
import json
import math
import random

PERIOD = 7
# 业务硬门槛：不足49天拒绝（两个完整周期初始化 + 至少一周完整回测折）。
MIN_DAYS = 49
WEEKDAY_CN = "一二三四五六日"


def metadata():
    return {
        "name": "食堂备餐需求预估", "short": "meal-seasonal",
        "tagline": "保留星期节律、按周滚动回测再出备餐建议，把缓冲量单独列明。",
        "client": "东港研发园 · 3人食堂计划组 · 单一午餐档112天实际领餐量",
        "workflow": "计划员按上周同日复制数量，再凭经验加餐，事后用剩餐记录复盘。",
        "pains": ["简单照搬上周忽略缓慢增长趋势", "单次留出碰上淡周显得偏准，需要逐周滚动验证", "预测误差与人为安全缓冲混在一起"],
        "upstream": "每日午餐实际核销份数 lunch_actual_20260720_20261108.csv",
        "downstream": "计划组审核未来7~21天备餐份数，采购与厨房据审核结果安排批次",
        "entities": ["每日领餐观测", "周期预测试验", "备餐审核简报"],
        "dataset_name": "东港园午餐112天实际领餐记录",
        "columns": [{"key": "date", "label": "领餐日期", "type": "string"}, {"key": "demand", "label": "实际领餐份数", "type": "number"}, {"key": "meal", "label": "档口", "type": "string"}],
        "parameters": [{"key": "alpha", "label": "水平平滑系数α", "type": "number", "default": 0.35, "min": 0.1, "max": 0.9}, {"key": "horizon", "label": "预测天数", "type": "number", "default": 7, "min": 7, "max": 21}, {"key": "safety_pct", "label": "计划安全缓冲(%)", "type": "number", "default": 8, "min": 0, "max": 20}],
        "workbench_title": "星期周期与备餐缓冲试算", "action_label": "按周滚动回测并生成备餐建议", "unit": "日观测",
        "accent": "oklch(58% 0.12 80)", "style": "kitchen-sheet-archive-press",
        "seed_story": ["06:30 计划员导入 lunch_actual_20260720_20261108.csv 的112天记录", "06:40 校验每天一条且连续，午餐档口一致", "06:50 以α=0.35、预测7天和8%缓冲创建试验", "06:51 后端按周滚动留出，每折只用截止日前记录预测随后7天", "07:00 计划员逐周比较Holt-Winters与上周同日基线的误差", "07:10 查看未来每日预测、缓冲份数和最终建议", "07:20 将缓冲改为12%比较备餐占用（回测不随缓冲变化）", "07:30 下载建议表，审核后交厨房批次计划", "16:30 管理员设每日16:30内部简报归档"],
        "method": "周期7天的加法Holt-Winters；α可调，趋势β=0.15、季节γ=0.20。按周滚动回测：每折训练截止日逐周推进，仅用截止日及之前记录预测随后7天，并与上周同日季节朴素法逐日对账；MAE与WAPE按全部对账日的误差分子分母加总计算，不平均各周百分比。全部历史重拟合后预测未来，建议份数=ceil(基础预测×(1+缓冲比例))，缓冲只改变建议量。",
        "limitations": ["未接入节假日、会议或园区停工信息", "安全缓冲是计划参数，不是统计置信区间", "仅适用于单一档口的连续每日数据"],
    }


def seed_records():
    rng = random.Random(1014)
    start = date(2026, 7, 20)
    weekday = [480, 520, 550, 530, 470, 180, 140]
    rows = []
    for i in range(112):
        current = start + timedelta(days=i)
        # 与旧版 numpy 口径保持一致的高斯扰动（Box-Muller）。
        u1 = max(1e-12, rng.random())
        u2 = rng.random()
        normal = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        demand = max(0, int(round(weekday[current.weekday()] + 0.45 * i + normal * 13)))
        rows.append({"date": current.isoformat(), "demand": demand, "meal": "东港园午餐"})
    return rows


def _forecast(values, horizon, alpha):
    """加法Holt-Winters递推；初始化只使用训练窗口前两个周期。

    纯标准库实现，数值口径与此前的 numpy 版本一致。
    """
    values = [float(v) for v in values]
    n = len(values)
    level = sum(values[:PERIOD]) / PERIOD
    level_second = sum(values[PERIOD:2 * PERIOD]) / PERIOD
    trend = (level_second - level) / PERIOD
    seasons = [v - level for v in values[:PERIOD]]
    beta, gamma = 0.15, 0.20
    for index in range(PERIOD, n):
        slot = index % PERIOD
        previous_level = level
        previous_season = seasons[slot]
        level = alpha * (values[index] - previous_season) + (1 - alpha) * (level + trend)
        trend = beta * (level - previous_level) + (1 - beta) * trend
        seasons[slot] = gamma * (values[index] - level) + (1 - gamma) * previous_season
    result = []
    for step in range(1, horizon + 1):
        slot = (n + step - 1) % PERIOD
        result.append(max(0.0, level + step * trend + seasons[slot]))
    return result


def _validate(records, params):
    """统一参数与记录校验，返回 (alpha, horizon, safety, 排序后的(日期,份数)列表)。"""
    try:
        alpha = float(params.get("alpha", 0.35))
        raw_horizon = float(params.get("horizon", 7))
        horizon = int(raw_horizon)
        safety = float(params.get("safety_pct", 8))
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("平滑系数、天数和安全缓冲须为有效数值。") from exc
    if not 0.1 <= alpha <= 0.9 or raw_horizon != horizon or not 7 <= horizon <= 21 or not 0 <= safety <= 20:
        raise ValueError("α须0.1~0.9，预测天数须7~21整数，缓冲须0~20%。")
    if len(records) < MIN_DAYS:
        raise ValueError("至少需要连续49天记录，以保证两个完整周期初始化并保留一周滚动回测。")
    parsed = []
    meals = set()
    for row in records:
        try:
            day = date.fromisoformat(str(row["date"]))
            value = float(row["demand"])
            meal = str(row["meal"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("日期须YYYY-MM-DD，份数须非负数，档口须完整。") from exc
        if not math.isfinite(value) or value < 0 or not meal:
            raise ValueError("领餐份数须非负有限，档口不能为空。")
        parsed.append((day, value))
        meals.add(meal)
    if len(meals) != 1:
        raise ValueError("一次仅分析一个档口，请先按档口拆分数据。")
    parsed.sort(key=lambda pair: pair[0])
    if any((parsed[i][0] - parsed[i - 1][0]).days != 1 for i in range(1, len(parsed))):
        raise ValueError("每日须恰好一条连续记录；停餐日请显式补0，不可跳日或重复。")
    return alpha, horizon, safety, parsed


def _rolling_backtest(values, dates, alpha):
    """按周滚动回测，返回 (折列表, 汇总字典)。

    每折训练窗口为 values[:cut]，验证窗口为随后7天；cut 从 2*PERIOD 起，
    逐周推进，直到剩余记录不足完整7天。
    """
    folds = []
    total_abs = 0.0          # 各折 |实际-预测| 分子加总
    total_naive_abs = 0.0    # 各折 |实际-上周同日| 分子加总
    total_actual = 0.0       # 各折实际量分母加总
    total_days = 0
    total_signed = 0.0       # 预测-实际 的带符号差，用于观察系统性偏差
    cut = 2 * PERIOD
    fold_no = 0
    while cut + PERIOD <= len(values):
        fold_no += 1
        train = values[:cut]
        actual = values[cut:cut + PERIOD]
        predicted = _forecast(train, PERIOD, alpha)
        naive = list(train[-PERIOD:])  # 上周同日：训练窗口最后7天
        days = []
        fold_abs = fold_naive_abs = fold_actual = fold_signed = 0.0
        for offset in range(PERIOD):
            day = dates[cut + offset]
            act = float(actual[offset])
            pred = float(predicted[offset])
            base = float(naive[offset])
            diff = pred - act
            naive_diff = base - act
            fold_abs += abs(diff)
            fold_naive_abs += abs(naive_diff)
            fold_actual += act
            fold_signed += diff
            days.append({
                "date": day.isoformat(),
                "weekday": "周" + WEEKDAY_CN[day.weekday()],
                "actual": round(act, 1),
                "forecast": round(pred, 1),
                "naive": round(base, 1),
                "diff": round(diff, 1),
                "naive_diff": round(naive_diff, 1),
                "abs_error": round(abs(diff), 1),
                "naive_abs_error": round(abs(naive_diff), 1),
            })
        total_abs += fold_abs
        total_naive_abs += fold_naive_abs
        total_actual += fold_actual
        total_signed += fold_signed
        total_days += PERIOD
        cutoff_day = dates[cut - 1]
        folds.append({
            "fold": fold_no,
            "train_cutoff": cutoff_day.isoformat(),
            "train_days": cut,
            "window_start": dates[cut].isoformat(),
            "window_end": dates[cut + PERIOD - 1].isoformat(),
            "mae": round(fold_abs / PERIOD, 2),
            "naive_mae": round(fold_naive_abs / PERIOD, 2),
            "actual_sum": round(fold_actual, 1),
            "abs_error_sum": round(fold_abs, 1),
            "naive_abs_error_sum": round(fold_naive_abs, 1),
            "bias_sum": round(fold_signed, 1),
            "days": days,
        })
        cut += PERIOD
    if not folds:
        raise ValueError("记录不足以形成完整的7天滚动回测折。")
    if total_actual <= 0:
        raise ValueError("全部回测日实际领餐量总和须大于0，否则WAPE无定义。")
    aggregate = {
        "folds": len(folds),
        "days": total_days,
        "mae": round(total_abs / total_days, 2),
        "naive_mae": round(total_naive_abs / total_days, 2),
        "wape": round(total_abs / total_actual * 100, 2),
        "naive_wape": round(total_naive_abs / total_actual * 100, 2),
        "abs_error_sum": round(total_abs, 1),
        "naive_abs_error_sum": round(total_naive_abs, 1),
        "actual_sum": round(total_actual, 1),
        "bias_sum": round(total_signed, 1),
        "rule": "各周绝对误差与实际量分别加总后计算MAE/WAPE，不平均各周百分比。",
    }
    return folds, aggregate


def _records_fingerprint(records):
    payload = json.dumps(records, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def analyze(records, params):
    alpha, horizon, safety, parsed = _validate(records, params)
    dates = [pair[0] for pair in parsed]
    values = [pair[1] for pair in parsed]
    folds, aggregate = _rolling_backtest(values, dates, alpha)

    future = _forecast(values, horizon, alpha)
    rows = []
    for i, value in enumerate(future, 1):
        day = dates[-1] + timedelta(days=i)
        planned = int(math.ceil(value * (1 + safety / 100) - 1e-9))
        rows.append({"date": day.isoformat(), "weekday": "周" + WEEKDAY_CN[day.weekday()], "forecast": round(value, 1), "buffer": round(planned - value, 1), "plan": planned})

    wape, naive_wape = aggregate["wape"], aggregate["naive_wape"]
    backtest_columns = [
        {"key": "fold", "label": "周次"},
        {"key": "train_cutoff", "label": "训练截止日"},
        {"key": "window_start", "label": "预测周起"},
        {"key": "window_end", "label": "预测周止"},
        {"key": "train_days", "label": "训练天数"},
        {"key": "mae", "label": "HW周MAE(份)"},
        {"key": "naive_mae", "label": "上周同日周MAE(份)"},
        {"key": "abs_error_sum", "label": "周绝对误差合计(份)"},
        {"key": "actual_sum", "label": "周实领合计(份)"},
        {"key": "bias_sum", "label": "周带符号差合计(份)"},
    ]
    daily_columns = [
        {"key": "date", "label": "对账日期"},
        {"key": "weekday", "label": "星期"},
        {"key": "actual", "label": "实领(份)"},
        {"key": "forecast", "label": "HW预测(份)"},
        {"key": "diff", "label": "HW差(预测-实领)"},
        {"key": "naive", "label": "上周同日(份)"},
        {"key": "naive_diff", "label": "基线差(基线-实领)"},
        {"key": "abs_error", "label": "HW绝对误差(份)"},
    ]
    fingerprint = _records_fingerprint(records)
    return {
        "summary": (
            f"按周滚动回测共{aggregate['folds']}折、覆盖{aggregate['days']}个对账日；"
            f"误差按各周分子分母加总，WAPE为{wape:.2f}%（上周同日基线{naive_wape:.2f}%）；"
            f"再以全部{len(values)}天重拟合预测未来{horizon}天，单列{safety:g}%计划缓冲。"
        ),
        "metrics": [
            {"label": "滚动回测MAE", "value": aggregate["mae"], "unit": "份/天"},
            {"label": "滚动回测WAPE", "value": aggregate["wape"], "unit": "%"},
            {"label": "上周同日基线WAPE", "value": aggregate["naive_wape"], "unit": "%"},
            {"label": "滚动折数", "value": aggregate["folds"], "unit": "折"},
            {"label": "预测期建议总量", "value": sum(row["plan"] for row in rows), "unit": "份"},
        ],
        "table": {"columns": [{"key": "date", "label": "预测日期"}, {"key": "weekday", "label": "星期"}, {"key": "forecast", "label": "基础预测(份)"}, {"key": "buffer", "label": "额外缓冲(份)"}, {"key": "plan", "label": "建议备餐(份)"}], "rows": rows},
        "chart": {"type": "line", "labels": [row["date"] for row in rows], "series": [{"name": "基础预测", "values": [row["forecast"] for row in rows]}, {"name": "含缓冲备餐建议", "values": [row["plan"] for row in rows]}]},
        "backtest": {
            "title": "按周滚动回测（每折仅用训练截止日及之前记录）",
            "aggregate": aggregate,
            "columns": backtest_columns,
            "rows": [{k: f[k] for k in ["fold", "train_cutoff", "window_start", "window_end", "train_days", "mae", "naive_mae", "abs_error_sum", "actual_sum", "bias_sum"]} for f in folds],
            "daily_columns": daily_columns,
            "folds": folds,
        },
        "findings": [
            f"滚动WAPE相对上周同日基线变化{wape - naive_wape:+.2f}个百分点（负值表示HW改善）；该口径汇总自{aggregate['folds']}折共{aggregate['days']}天，未平均各周百分比。",
            f"全部对账日HW绝对误差合计{aggregate['abs_error_sum']:.1f}份、实领合计{aggregate['actual_sum']:.1f}份；带符号差合计{aggregate['bias_sum']:+.1f}份（正为整体高估）。",
            f"未来{horizon}天基础预测合计{sum(future):.1f}份，建议合计{sum(row['plan'] for row in rows)}份。",
            "先审核特殊活动和休园日，再确认备餐批次；缓冲只改变建议份数，不改变回测指标与基础预测。",
        ],
        "method": metadata()["method"],
        "warnings": ["节假日与活动尚未作为外生变量；缓冲不是置信区间。"] + (["滚动回测中模型未优于上周同日基线，应优先复核趋势与异常日。"] if wape >= naive_wape else []),
        "snapshot": {
            "record_count": len(records),
            "date_start": dates[0].isoformat(),
            "date_end": dates[-1].isoformat(),
            "checksum": fingerprint,
            "alpha": alpha,
            "horizon": horizon,
            "safety_pct": safety,
            "note": "本结果永久绑定试验运行时所用记录快照与参数；源批次更新不会改写本任务，重算请基于新批次另建试验。",
        },
    }
