"""雨水调蓄池连续时间推演引擎。

状态量（SI 单位）:
  水量 V (m³)、管道累计过水量 (m³)、泵累计排量 (m³)、各池累计溢流 (m³)
水头 H = 池底高程 + 水量 / 截面积
管道请求流量 q = coeff * sqrt(max(0, H_from - H_to))

边界处理（投影动力学，连续且 Lipschitz/Hölder，可直接由 solve_ivp 积分）:
  空池 V=0：若来水不足以满足出管/泵请求，各出流按请求量比例限流；
  满池 V=cap：净余水量计溢流，水量变化钳为非正。
事件仅用于泵的滞回切换（升至启位开、降至停位关）。
"""
from __future__ import annotations

import numpy as np
from scipy.integrate import solve_ivp

T_TIME = 1e-8


class SimError(ValueError):
    """推演失败（输入不合法或数值失败）。"""


def simulate(cfg: dict) -> dict:
    tanks = cfg["tanks"]
    intervals = cfg.get("intervals", [])
    pipes = cfg.get("pipes", [])
    pumps = cfg.get("pumps", [])
    duration = float(cfg["duration"])

    n = len(tanks)
    n_pipe, n_pump = len(pipes), len(pumps)

    idx = {t["id"]: i for i, t in enumerate(tanks)}
    bottom = np.array([t["bottom"] for t in tanks], dtype=float)
    area = np.array([t["area"] for t in tanks], dtype=float)
    cap = np.array([t["capacity"] for t in tanks], dtype=float)
    v0 = np.array([t["initial_volume"] for t in tanks], dtype=float)

    # ---- 分段恒定非负入流：合并到统一断点网格 ----
    bk = {0.0, duration}
    for seg in intervals:
        bk.add(float(seg["start"]))
        bk.add(float(seg["end"]))
    bkpts = np.array(sorted(bk), dtype=float)
    inflow = np.zeros((n, len(bkpts) - 1))
    for seg in intervals:
        a, b = float(seg["start"]), float(seg["end"])
        la = int(np.searchsorted(bkpts, a))
        lb = int(np.searchsorted(bkpts, b))
        for k in range(la, lb):
            inflow[idx[seg["tank"]], k] += float(seg["flow"])

    pf = np.array([idx[p["from"]] for p in pipes], dtype=int)
    pt = np.array([idx[p["to"]] for p in pipes], dtype=int)
    pcoef = np.array([p["coeff"] for p in pipes], dtype=float)
    pu_tank = np.array([idx[p["tank"]] for p in pumps], dtype=int)
    pu_q = np.array([p["flow"] for p in pumps], dtype=float)
    d_on = np.array([p["on_depth"] for p in pumps], dtype=float)
    d_off = np.array([p["off_depth"] for p in pumps], dtype=float)
    pump_on = np.array([bool(p["initial_on"]) for p in pumps])

    # 增强状态布局
    iv = np.arange(n)
    ip = n + np.arange(n_pipe)
    iu = n + n_pipe + np.arange(n_pump)
    io_ = n + n_pipe + n_pump + np.arange(n)
    n_state = n + n_pipe + n_pump + n

    y = np.zeros(n_state)
    y[iv] = v0

    v_scale = max(1.0, float(np.max(cap)))
    eps_v = 1e-9 * v_scale   # 数值意义上的"贴空"

    seg_k = 0

    def quants(V):
        """给定水量计算全部实现流量；返回各分量与 dv、溢流率。"""
        h = bottom + np.maximum(V, 0.0) / area

        if n_pipe:
            dh = h[pf] - h[pt]
            qreq = pcoef * np.sqrt(np.maximum(0.0, dh))
            pipe_dem = np.zeros(n)
            np.add.at(pipe_dem, pf, qreq)
        else:
            qreq = np.zeros(0)
            pipe_dem = np.zeros(n)

        pump_dem = np.zeros(n)
        if n_pump:
            for u in range(n_pump):
                if pump_on[u]:
                    pump_dem[pu_tank[u]] += pu_q[u]

        ext = inflow[:, seg_k] if inflow.size else np.zeros(n)
        demand = pipe_dem + pump_dem

        # 固定点求各"贴空"池的限流比例 alpha = min(1, 可用来水/总请求)
        alpha = np.ones(n)
        empty = V <= eps_v
        for _ in range(2000):
            up = np.zeros(n)
            if n_pipe:
                np.add.at(up, pt, qreq * alpha[pf])
            avail = ext + up
            new = np.ones(n)
            ratio = np.ones(n)
            pos = demand > 0.0
            ratio[pos] = np.minimum(1.0, avail[pos] / demand[pos])
            new[empty] = ratio[empty]
            new[empty & (demand <= 0.0)] = 1.0
            diff = float(np.max(np.abs(new - alpha)))
            alpha = new
            if diff < 1e-12:
                break

        f_pipe = qreq * alpha[pf] if n_pipe else qreq
        f_pump = (pu_q * alpha[pu_tank] * pump_on.astype(float)
                  if n_pump else pu_q)

        pin = np.zeros(n)
        pout = np.zeros(n)
        pp = np.zeros(n)
        if n_pipe:
            np.add.at(pin, pf, f_pipe)
            np.add.at(pout, pt, f_pipe)
        if n_pump:
            for u in range(n_pump):
                pp[pu_tank[u]] += f_pump[u]

        g = ext + pout - pin - pp

        # 空边界：水量变化非负（来水不足时出流已被比例限流）
        dv = g.copy()
        dv[V <= eps_v] = np.maximum(0.0, g[V <= eps_v])

        # 满边界：净余水量计溢流，水量变化非正
        ovr = np.zeros(n)
        full = V >= cap - eps_v
        ovr[full] = np.maximum(0.0, g[full])
        dv[full] = np.minimum(0.0, g[full])

        return f_pipe, f_pump, dv, ovr

    def rhs(t, yv):
        V = yv[iv]
        f_pipe, f_pump, dv, ovr = quants(V)
        d = np.zeros(n_state)
        d[iv] = dv
        if n_pipe:
            d[ip] = f_pipe
        if n_pump:
            d[iu] = f_pump
        d[io_] = ovr
        if not np.all(np.isfinite(d)):
            return np.full(n_state, np.nan)
        return d

    switches = []

    def build_events():
        """泵滞回事件：关->升至启位开；开->降至停位关。"""
        evs = []
        for u in range(n_pump):
            ti = pu_tank[u]
            if not pump_on[u]:
                def on_ev(t, yv, u=u):
                    return yv[pu_tank[u]] / area[pu_tank[u]] - d_on[u]
                on_ev.terminal = True
                on_ev.direction = 1
                evs.append((u, True, on_ev))
            else:
                def off_ev(t, yv, u=u):
                    return yv[pu_tank[u]] / area[pu_tank[u]] - d_off[u]
                off_ev.terminal = True
                off_ev.direction = -1
                evs.append((u, False, off_ev))
        return evs

    pieces = []
    tcur = 0.0
    k = 0
    guard = 0
    while tcur < duration - T_TIME:
        tend = float(bkpts[k + 1])
        seg_k = k
        evs = build_events()
        try:
            sol = solve_ivp(
                rhs, (tcur, tend), y, method="RK45",
                dense_output=True, events=[e[2] for e in evs],
                rtol=1e-9, atol=1e-9,
                max_step=(tend - tcur) if tend > tcur else np.inf)
        except Exception as exc:  # noqa: BLE001
            raise SimError(f"数值积分失败: {exc}") from exc
        if not sol.success:
            raise SimError(f"数值积分失败: {sol.message}")

        if sol.status == 1:
            roots = []
            for ei, arr in enumerate(sol.t_events):
                for r in arr:
                    if r > tcur + T_TIME:
                        roots.append((float(r), ei))
            if not roots:
                pieces.append((tcur, tend, sol))
                tcur = tend
                y = sol.y[:, -1]
            else:
                rmin = min(r for r, _ in roots)
                yroot = sol.sol(rmin)
                # 数值钳位，杜绝负水量/超容量
                yroot[iv] = np.minimum(np.maximum(yroot[iv], 0.0), cap)
                pieces.append((tcur, rmin, sol))
                tcur = rmin
                y = yroot
                # 同刻先切换泵（同刻的多个泵事件一并处理）
                for r, ei in roots:
                    if r <= rmin + T_TIME:
                        u, turn_on, _ = evs[ei]
                        if turn_on and not pump_on[u]:
                            pump_on[u] = True
                            switches.append(dict(time=r, pump=pumps[u]["id"],
                                                 action="开启"))
                        elif not turn_on and pump_on[u]:
                            pump_on[u] = False
                            switches.append(dict(time=r, pump=pumps[u]["id"],
                                                 action="关闭"))
            # 事件若恰落在断点，推进入流区间
            if tcur >= tend - T_TIME and tcur < duration - T_TIME:
                k += 1
                seg_k = k
        else:
            pieces.append((tcur, tend, sol))
            tcur = tend
            y = sol.y[:, -1]
            k += 1
            seg_k = k

        guard += 1
        if guard > 1_000_000:
            raise SimError("事件次数超限，疑似数值颤振")

    if tcur < duration - 1e-6:
        raise SimError("推演未覆盖完整时段")

    # ---- 统一时间网格采样（含断点与泵事件时刻）----
    ev_times = sorted({s["time"] for s in switches})
    ngrid = min(800, max(300, int(duration * 2)))
    grid = np.unique(np.concatenate(
        [np.linspace(0.0, duration, ngrid), bkpts,
         np.array(ev_times if ev_times else [])]))
    Y = np.zeros((n_state, len(grid)))
    pi = 0
    for j, tg in enumerate(grid):
        while pi < len(pieces) - 1 and tg > pieces[pi][1] + T_TIME:
            pi += 1
        a, b, sol = pieces[pi]
        tt = min(max(tg, a), b)
        Y[:, j] = sol.sol(tt)

    Vm = np.minimum(np.maximum(Y[iv, :], 0.0), cap[:, None])
    depth = Vm / area[:, None]
    head = bottom[:, None] + depth
    cum_pipe = Y[ip, :] if n_pipe else np.zeros((0, len(grid)))
    cum_pump = Y[iu, :] if n_pump else np.zeros((0, len(grid)))
    cum_over = Y[io_, :]

    # ---- 收支校核：初存 + 入流 = 末存 + 泵排 + 溢流 ----
    total_in = float(np.sum(inflow * np.diff(bkpts)[None, :])) if inflow.size else 0.0
    initial = float(np.sum(v0))
    final = float(np.sum(Vm[:, -1]))
    pumped = float(np.sum(cum_pump[:, -1])) if n_pump else 0.0
    over = float(np.sum(cum_over[:, -1]))
    residual = initial + total_in - final - pumped - over
    tol = 1e-6 * max(1.0, initial + total_in, float(np.sum(cap))) + 1e-7
    if abs(residual) > tol:
        raise SimError(f"水量收支不闭合，残差 {residual:.6g} m³ 超过容差 {tol:.6g} m³")
    if np.any(Y[iv, :] < -1e-6 * v_scale):
        raise SimError("推演出现负水量，计算失败")

    return dict(
        times=[float(x) for x in grid],
        duration=duration,
        tanks=[dict(
            id=tanks[i]["id"], bottom=float(bottom[i]), area=float(area[i]),
            capacity=float(cap[i]),
            depth=[float(x) for x in depth[i]],
            head=[float(x) for x in head[i]],
            volume=[float(x) for x in Vm[i]],
            overflow=[float(x) for x in cum_over[i]],
            overflow_total=float(cum_over[i, -1]),
        ) for i in range(n)],
        pipes=[dict(
            id=pipes[p]["id"], **{"from": pipes[p]["from"], "to": pipes[p]["to"]},
            coeff=float(pcoef[p]),
            cumulative=[float(x) for x in cum_pipe[p]],
            total=float(cum_pipe[p, -1]),
        ) for p in range(n_pipe)],
        pumps=[dict(
            id=pumps[u]["id"], tank=pumps[u]["tank"], flow=float(pu_q[u]),
            on_depth=float(d_on[u]), off_depth=float(d_off[u]),
            cumulative=[float(x) for x in cum_pump[u]],
            total=float(cum_pump[u, -1]),
            switches=[s for s in switches if s["pump"] == pumps[u]["id"]],
        ) for u in range(n_pump)],
        summary=dict(
            initial_storage=initial,
            total_inflow=total_in,
            final_storage=final,
            total_pumped=pumped,
            total_overflow=over,
            balance_residual=residual,
        ),
        switches=sorted(switches, key=lambda s: s["time"]),
    )
