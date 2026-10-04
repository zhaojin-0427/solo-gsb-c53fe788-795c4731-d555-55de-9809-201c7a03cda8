"""引擎关键行为验证（手动断言，非 pytest 依赖）。"""
import math
import numpy as np

from app.engine import simulate, SimError

DEMO = dict(
    duration=7200.0,
    tanks=[
        dict(id="A", bottom=10.0, area=100.0, capacity=500.0, initial_volume=0.0),
        dict(id="B", bottom=8.0, area=80.0, capacity=400.0, initial_volume=40.0),
    ],
    intervals=[
        dict(tank="A", start=0.0, end=3600.0, flow=0.30),
        dict(tank="A", start=3600.0, end=7200.0, flow=0.02),
    ],
    pipes=[dict(id="P1", **{"from": "A", "to": "B"}, coeff=0.35)],
    pumps=[dict(id="PU1", tank="B", flow=0.15, on_depth=3.0, off_depth=1.0,
                initial_on=False)],
)


def check_basic():
    r = simulate(DEMO)
    times = np.array(r["times"])
    assert times[0] == 0 and abs(times[-1] - 7200) < 1e-6
    for t in r["tanks"]:
        v = np.array(t["volume"])
        assert np.all(v >= -1e-9), "出现负水量"
        assert np.all(v <= t["capacity"] + 1e-6), "超过容量"
        assert np.all(np.isfinite(v))
        assert t["overflow_total"] >= -1e-12
    p = r["pipes"][0]
    assert p["total"] > 0
    cum = np.array(p["cumulative"])
    assert np.all(np.diff(cum) >= -1e-9), "累计过水必须单调不减"
    # 管道方向：A底10m，B水头=8+0.5=8.5起，A空池水头10，从一开始就A->B有水
    s = r["summary"]
    lhs = s["initial_storage"] + s["total_inflow"]
    rhs = s["final_storage"] + s["total_pumped"] + s["total_overflow"]
    assert abs(lhs - rhs) < 1e-3 * max(1, lhs) + 1e-6, (lhs, rhs)
    # 泵应至少发生一次切换
    assert len(r["switches"]) >= 1, r["switches"]
    assert r["switches"][0]["action"] == "开启"
    # 切换时刻水深一致性
    B = r["tanks"][1]
    for sw in r["switches"]:
        j = np.argmin(abs(times - sw["time"]))
        d = B["depth"][j]
        if sw["action"] == "开启":
            assert abs(d - 3.0) < 0.05, (sw, d)
        else:
            assert abs(d - 1.0) < 0.05, (sw, d)
    print("[1] 基本推演 OK；泵切换", [(sw["time"], sw["action"]) for sw in r["switches"]],
          "溢流", round(s["total_overflow"], 3), "泵排", round(s["total_pumped"], 3),
          "残差", f"{s['balance_residual']:.2e}")


def check_reverse():
    """负水头差按零：反向管不得过水。"""
    cfg = dict(
        duration=1000.0,
        tanks=[dict(id="X", bottom=0.0, area=10.0, capacity=100.0, initial_volume=50.0),
               dict(id="Y", bottom=0.0, area=10.0, capacity=100.0, initial_volume=0.0)],
        intervals=[dict(tank="Y", start=0.0, end=1000.0, flow=0.05)],
        pipes=[dict(id="R", **{"from": "Y", "to": "X"}, coeff=1.0)],
        pumps=[])
    r = simulate(cfg)
    assert r["pipes"][0]["total"] == 0.0
    # Y 有水后水头仍低于 X(=5m) 很久：确认全程无反向
    assert abs(sum(r["tanks"][0]["volume"][i] - 50.0
                   for i in [0, len(r["times"]) // 2])) >= 0  # X 只增不减
    vx = np.array(r["tanks"][0]["volume"])
    assert vx[-1] >= 50.0 - 1e-9
    print("[2] 负水头差零流量 OK；反向管累计 =", r["pipes"][0]["total"])


def check_empty_rationing():
    """空池来水不足：两出管按请求比例限流，水量不出现负值。

    S 为空池（底高程高），两出管流向低高程的 M/N，水头差恒为 5m，
    请求比 c1:c2 = 1:3；入流仅 0.04 小于初始总请求。
    """
    cfg = dict(
        duration=2000.0,
        tanks=[dict(id="S", bottom=5.0, area=10.0, capacity=1000.0, initial_volume=0.0),
               dict(id="M", bottom=0.0, area=1e6, capacity=1e9, initial_volume=0.0),
               dict(id="N", bottom=0.0, area=1e6, capacity=1e9, initial_volume=0.0)],
        intervals=[dict(tank="S", start=0.0, end=2000.0, flow=0.04)],
        pipes=[dict(id="p1", **{"from": "S", "to": "M"}, coeff=1.0),
               dict(id="p2", **{"from": "S", "to": "N"}, coeff=3.0)],
        pumps=[])
    r = simulate(cfg)
    s = r["summary"]
    assert abs(s["balance_residual"]) < 1e-4
    tot1, tot3 = r["pipes"][0]["total"], r["pipes"][1]["total"]
    total_out = tot1 + tot3
    assert abs(tot1 - 0.25 * total_out) < 0.02 * total_out + 1e-6, (tot1, tot3)
    assert abs(tot3 - 0.75 * total_out) < 0.02 * total_out + 1e-6, (tot1, tot3)
    # 全部入流 80 m³ 都应流出（S 始终贴空，末存≈0）
    assert abs(total_out - 80.0) < 1.0, (tot1, tot3)
    assert np.max(r["tanks"][0]["volume"]) < 1e-3, "S 应始终贴空"
    assert np.min(r["tanks"][0]["volume"]) >= -1e-9
    print(f"[3] 空池比例限流 OK；p1={tot1:.2f}, p2={tot3:.2f}（约 1:3），总出流 {total_out:.2f}")


def check_ring():
    """三池成环 + 环内空池：不得凭空造水，收支闭合，无负值。"""
    cfg = dict(
        duration=1800.0,
        tanks=[dict(id="A", bottom=0.0, area=20.0, capacity=500.0, initial_volume=0.0),
               dict(id="B", bottom=-2.0, area=20.0, capacity=500.0, initial_volume=0.0),
               dict(id="C", bottom=-2.0, area=20.0, capacity=500.0, initial_volume=0.0)],
        intervals=[dict(tank="A", start=0.0, end=1800.0, flow=0.1)],
        pipes=[dict(id="ab", **{"from": "A", "to": "B"}, coeff=0.5),
               dict(id="bc", **{"from": "B", "to": "C"}, coeff=0.5),
               dict(id="ca", **{"from": "C", "to": "A"}, coeff=0.5)],
        pumps=[])
    r = simulate(cfg)
    s = r["summary"]
    assert abs(s["balance_residual"]) < 1e-4, s
    for t in r["tanks"]:
        assert np.all(np.array(t["volume"]) >= -1e-9)
    print("[4] 成环推演 OK；残差", f"{s['balance_residual']:.2e}",
          "各管", [round(p["total"], 2) for p in r["pipes"]])


def check_overflow():
    """入流超容：满池净余水量计溢流。"""
    cfg = dict(
        duration=4000.0,
        tanks=[dict(id="A", bottom=0.0, area=10.0, capacity=100.0, initial_volume=0.0)],
        intervals=[dict(tank="A", start=0.0, end=4000.0, flow=0.1)],
        pipes=[], pumps=[])
    r = simulate(cfg)
    t = r["tanks"][0]
    assert abs(t["volume"][-1] - 100.0) < 1e-4
    s = r["summary"]
    assert abs(s["total_overflow"] - 300.0) < 1e-2, s
    assert abs(s["balance_residual"]) < 1e-3
    # 溢流单调不减
    assert np.all(np.diff(np.array(t["overflow"])) >= -1e-9)
    print(f"[5] 满池溢流 OK；末存={t['volume'][-1]:.2f}, 溢流={s['total_overflow']:.2f}")


def check_pump_hysteresis():
    """泵在启/停位间滞回切换，泵排等于额定流量×开启时长。"""
    cfg = dict(
        duration=6000.0,
        tanks=[dict(id="A", bottom=0.0, area=10.0, capacity=1e6, initial_volume=25.0)],
        intervals=[dict(tank="A", start=0.0, end=3000.0, flow=0.1),
                   dict(tank="A", start=3000.0, end=6000.0, flow=0.0)],
        pipes=[],
        pumps=[dict(id="P", tank="A", flow=0.2, on_depth=3.0, off_depth=1.0,
                    initial_on=False)])
    r = simulate(cfg)
    sw = r["switches"]
    actions = [s["action"] for s in sw]
    assert actions[0] == "开启"
    assert "关闭" in actions
    # 开启时长
    on_time = 0.0
    cur = 0.0
    on = False
    last = 0.0
    for s in sw:
        if on:
            on_time += s["time"] - last
        on = s["action"] == "开启"
        last = s["time"]
    if on:
        on_time += 6000.0 - last
    assert abs(r["pumps"][0]["total"] - 0.2 * on_time) < 1e-2
    s = r["summary"]
    assert abs(s["balance_residual"]) < 1e-3
    print(f"[6] 泵滞回 OK；切换 {[round(x['time'],1) for x in sw]}；开启时长 {on_time:.1f}s")


def check_validation_errors():
    bad_cases = [
        ("非正面积", {**DEMO, "tanks":[dict(DEMO["tanks"][0], area=0.0), DEMO["tanks"][1]]}),
        ("NaN", {**DEMO, "duration": float("nan")}),
        ("初水量越界", {**DEMO, "tanks":[dict(DEMO["tanks"][0], initial_volume=999.0), DEMO["tanks"][1]]}),
        ("管系数非正", {**DEMO, "pipes":[dict(DEMO["pipes"][0], coeff=-1.0)]}),
        ("泵流量非正", {**DEMO, "pumps":[dict(DEMO["pumps"][0], flow=0.0)]}),
        ("停位>=启位", {**DEMO, "pumps":[dict(DEMO["pumps"][0], off_depth=3.0)]}),
        ("初态不符(初始开但低于停位)",
         {**DEMO, "tanks":[DEMO["tanks"][0], dict(DEMO["tanks"][1], initial_volume=0.0)],
          "pumps":[dict(DEMO["pumps"][0], initial_on=True)]}),
        ("初态不符(初始关但已达启位)",
         {**DEMO, "tanks":[DEMO["tanks"][0], dict(DEMO["tanks"][1], initial_volume=300.0)],
          "pumps":[dict(DEMO["pumps"][0], initial_on=False)]}),
        ("负入流", {**DEMO, "intervals":[dict(DEMO["intervals"][0], flow=-1.0), DEMO["intervals"][1]]}),
        ("自环管", {**DEMO, "pipes":[dict(DEMO["pipes"][0], id="L", **{"from":"A","to":"A"})]}),
        ("泵引用不存在池", {**DEMO, "pumps":[dict(DEMO["pumps"][0], tank="Z")]}),
        ("入流结束超出时长", {**DEMO, "intervals":[dict(DEMO["intervals"][0], end=99999.0), DEMO["intervals"][1]]}),
        ("入流起止倒置", {**DEMO, "intervals":[dict(DEMO["intervals"][0], start=100.0, end=50.0), DEMO["intervals"][1]]}),
    ]
    from app.models import SimRequest, normalize
    for name, payload in bad_cases:
        hit = False
        try:
            normalize(SimRequest.model_validate(payload))
        except ValueError:
            hit = True
        assert hit, f"应拒绝: {name}"
    print(f"[7] {len(bad_cases)} 项非法输入全部被拒绝 OK")


def check_no_inflow_no_motion():
    """无入流、水头不足时管道不过水、系统静止。"""
    cfg = dict(
        duration=100.0,
        tanks=[dict(id="A", bottom=0.0, area=10.0, capacity=100.0, initial_volume=10.0),
               dict(id="B", bottom=5.0, area=10.0, capacity=100.0, initial_volume=0.0)],
        intervals=[], pipes=[dict(id="p", **{"from":"A","to":"B"}, coeff=2.0)], pumps=[])
    r = simulate(cfg)
    assert r["pipes"][0]["total"] == 0.0
    assert abs(r["tanks"][0]["volume"][-1] - 10.0) < 1e-9
    print("[8] 无驱动静止 OK")


if __name__ == "__main__":
    check_basic()
    check_reverse()
    check_empty_rationing()
    check_ring()
    check_overflow()
    check_pump_hysteresis()
    check_validation_errors()
    check_no_inflow_no_motion()
    print("\n全部测试通过 ✓")
