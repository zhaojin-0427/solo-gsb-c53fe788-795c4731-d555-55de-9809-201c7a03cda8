"""请求模型与输入校验。

所有规则性校验（非有限数值、非正面积/容量/系数/流量、初水量越界、
泵停位不低于启位、初态与阈值不符等）在此显式完成并给出中文错误。
"""
from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field


class TankIn(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    bottom: float
    area: float
    capacity: float
    initial_volume: float = Field(default=0.0, alias="initialVolume")


class IntervalIn(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    tank: str
    start: float
    end: float
    flow: float


class PipeIn(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    # from 是 Python 关键字，用字段名 from_ + 别名 from
    from_: str = Field(alias="from")
    to: str
    coeff: float

    def src(self) -> str:
        return self.from_


class PumpIn(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    tank: str
    flow: float
    on_depth: float = Field(alias="onDepth")
    off_depth: float = Field(alias="offDepth")
    initial_on: bool = Field(default=False, alias="initialOn")


class SimRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    duration: float
    tanks: list[TankIn]
    intervals: list[IntervalIn] = Field(default_factory=list)
    pipes: list[PipeIn] = Field(default_factory=list)
    pumps: list[PumpIn] = Field(default_factory=list)


def _finite(name: str, value: float) -> None:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} 必须为有限数值")


def normalize(req: SimRequest) -> dict:
    """把解析后的请求转为引擎所需 dict，并完成全部规则校验。"""
    if not math.isfinite(req.duration):
        raise ValueError("推演时长必须为有限数值")
    if req.duration <= 0:
        raise ValueError("推演时长必须为正数")
    if not req.tanks:
        raise ValueError("至少需要一个调蓄池")

    tank_ids: set[str] = set()
    tanks = []
    for j, t in enumerate(req.tanks):
        where = f"第 {j + 1} 个调蓄池（{t.id}）"
        if not str(t.id).strip():
            raise ValueError(f"{where}：编号不能为空")
        if t.id in tank_ids:
            raise ValueError(f"调蓄池编号重复: {t.id}")
        tank_ids.add(t.id)
        for name, v in (("池底高程", t.bottom), ("截面积", t.area),
                        ("容量", t.capacity), ("初始水量", t.initial_volume)):
            _finite(f"{where}的{name}", v)
        if t.area <= 0:
            raise ValueError(f"{where}：截面积必须为正数")
        if t.capacity <= 0:
            raise ValueError(f"{where}：容量必须为正数")
        if t.initial_volume < 0:
            raise ValueError(f"{where}：初始水量不能为负")
        if t.initial_volume > t.capacity:
            raise ValueError(f"{where}：初始水量超过容量")
        tanks.append(dict(id=t.id, bottom=float(t.bottom), area=float(t.area),
                          capacity=float(t.capacity),
                          initial_volume=float(t.initial_volume)))

    intervals = []
    for j, seg in enumerate(req.intervals):
        where = f"第 {j + 1} 个入流时段（池 {seg.tank}）"
        if seg.tank not in tank_ids:
            raise ValueError(f"{where}：所属池不存在")
        for name, v in (("开始时刻", seg.start), ("结束时刻", seg.end),
                        ("入流流量", seg.flow)):
            _finite(f"{where} 的{name}", v)
        if seg.start < 0 or seg.end < 0:
            raise ValueError(f"{where}：时刻不能为负")
        if seg.end <= seg.start:
            raise ValueError(f"{where}：结束时刻必须严格晚于开始时刻")
        if seg.start >= req.duration:
            raise ValueError(f"{where}：开始时刻超出推演时长")
        if seg.end > req.duration:
            raise ValueError(f"{where}：结束时刻超出推演时长")
        if seg.flow < 0:
            raise ValueError(f"{where}：入流流量不能为负")
        intervals.append(dict(tank=seg.tank, start=float(seg.start),
                              end=float(seg.end), flow=float(seg.flow)))

    pipe_ids: set[str] = set()
    pipes = []
    for j, p in enumerate(req.pipes):
        where = f"第 {j + 1} 条管道（{p.id}）"
        if not str(p.id).strip():
            raise ValueError(f"{where}：编号不能为空")
        if p.id in pipe_ids:
            raise ValueError(f"管道编号重复: {p.id}")
        pipe_ids.add(p.id)
        src, dst = p.src(), p.to
        if src not in tank_ids:
            raise ValueError(f"{where}：起点池不存在")
        if dst not in tank_ids:
            raise ValueError(f"{where}：终点池不存在")
        if src == dst:
            raise ValueError(f"{where}：管道起止池不能相同（单向重力管不得自环）")
        _finite(f"{where} 的系数", p.coeff)
        if p.coeff <= 0:
            raise ValueError(f"{where}：管道系数必须为正数")
        pipes.append(dict(id=p.id, **{"from": src, "to": dst},
                          coeff=float(p.coeff)))

    pump_ids: set[str] = set()
    pumps = []
    for j, pu in enumerate(req.pumps):
        where = f"第 {j + 1} 台泵（{pu.id}）"
        if not str(pu.id).strip():
            raise ValueError(f"{where}：编号不能为空")
        if pu.id in pump_ids:
            raise ValueError(f"泵编号重复: {pu.id}")
        pump_ids.add(pu.id)
        if pu.tank not in tank_ids:
            raise ValueError(f"{where}：所属池不存在")
        for name, v in (("排水流量", pu.flow), ("启泵水深", pu.on_depth),
                        ("停泵水深", pu.off_depth)):
            _finite(f"{where} 的{name}", v)
        if pu.flow <= 0:
            raise ValueError(f"{where}：泵流量必须为正数")
        if pu.off_depth >= pu.on_depth:
            raise ValueError(f"{where}：停泵水深必须严格小于启泵水深")
        if pu.off_depth < 0:
            raise ValueError(f"{where}：停泵水深不能为负")
        tank = next(t for t in tanks if t["id"] == pu.tank)
        dmax = tank["capacity"] / tank["area"]
        if pu.on_depth > dmax + 1e-12:
            raise ValueError(
                f"{where}：启泵水深 {pu.on_depth:g} m 超过该池最大水深 "
                f"{dmax:g} m，泵永远无法开启")
        # 初态与阈值一致性
        d0 = tank["initial_volume"] / tank["area"]
        if pu.initial_on and d0 < pu.off_depth - 1e-9:
            raise ValueError(
                f"{where}：初态为开启，但初始水深 {d0:g} m 已低于停泵水深 "
                f"{pu.off_depth:g} m，初态与阈值不符")
        if not pu.initial_on and d0 >= pu.on_depth + 1e-9:
            raise ValueError(
                f"{where}：初态为关闭，但初始水深 {d0:g} m 已达到启泵水深 "
                f"{pu.on_depth:g} m，初态与阈值不符")
        pumps.append(dict(id=pu.id, tank=pu.tank, flow=float(pu.flow),
                          on_depth=float(pu.on_depth),
                          off_depth=float(pu.off_depth),
                          initial_on=bool(pu.initial_on)))

    return dict(duration=float(req.duration), tanks=tanks,
                intervals=intervals, pipes=pipes, pumps=pumps)
