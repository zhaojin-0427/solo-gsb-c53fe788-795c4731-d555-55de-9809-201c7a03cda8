# 雨水调蓄池推演 Web 应用

基于 **Python + FastAPI + SciPy + 原生 JavaScript** 的雨水调蓄池连续时间推演系统：
给定时段、各池几何与初始水量、分段恒定非负入流、可成环的单向重力连接管以及排外泵参数，
推演各池水位/水头、管道累计过水量、泵切换时刻、溢流及水量收支。

## 一、Docker Compose 一键启动

```bash
docker compose up --build
```

启动后浏览器访问：

| 内容 | 地址 |
| --- | --- |
| 推演页面（输入参数、查看曲线与结果） | <http://localhost:8000/> |
| 健康检查 | <http://localhost:8000/api/health> |
| 接口文档（Swagger） | <http://localhost:8000/docs> |

停止：在另一个终端执行 `docker compose down`。

> 端口修改：编辑 `docker-compose.yml` 中 `"8000:8000"` 左侧端口即可。

### 本地（无 Docker）启动

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 二、页面使用与结果查看

1. 打开 <http://localhost:8000/>，点击 **“载入示例”** 可快速填入一套双池 + 管道 + 排外泵方案。
2. 填写/编辑五组参数：
   - **推演时长**（秒）；
   - **调蓄池**：编号、池底高程 (m)、截面积 (m²)、容量 (m³)、初始水量 (m³)；
   - **分段恒定入流**：所属池、起止时刻、非负流量 (m³/s)；
   - **重力管道**：起点池、终点池、系数 `c`（允许多管成环，水只能沿正水头差方向流动）；
   - **排外泵**：所属池、流量 (m³/s)、启泵水深、停泵水深、初始开关状态。
3. 点击 **“开始推演”**，页面显示：
   - **水位曲线**：可切换“水深（相对池底）/ 水头高程”；竖虚线为泵切换时刻，
     横虚线标注启/停泵水深与满池水深；
   - **管道累计过水量**：各管随时间累计值，图例给出最终总量；
   - **泵累计排量 / 各池累计溢流**曲线；
   - **泵切换时刻表**（开启/关闭及精确秒数）；
   - **溢流统计**与**水量收支**校核：`初存 + 入流 = 末存 + 泵排 + 溢流`，并给出闭合残差。
4. 校验不通过或计算失败时，页面顶部显示中文拒绝原因且**不会保留任何旧结果**。

## 三、推演模型

- 水头：`H_i = 池底高程_i + V_i / 面积_i`（空池水量钉在 0）。
- 管道请求流量（Orifice 型）：`q_p = c_p · sqrt(max(0, H_from − H_to))`，
  水头差为负时请求量为 0，**不存在反向流**。
- 泵滞回：水深升至启泵水深开启、降至停泵水深关闭，开启时按额定流量排到系统外。
- 连续时间推演（SciPy `solve_ivp` 事件驱动 RK45），联合处理三类“断点”：
  入流分段切换、泵开关切换、空/满边界事件；同一时刻**先更新入流与泵，再结算边界流量**。
- **空池限流**：空池来水不足以满足其全部出管/泵请求时，各出流按请求量比例限流
  （对含环管网以固定点一致求解各池限流比例），保证水量恒非负。
- **满池溢流**：满池的净余水量（入流 + 上游来水 − 下游需求 − 泵排）计作该池溢流。

## 四、输入校验（任一不满足即拒绝计算，HTTP 400）

- 出现非有限数值（NaN/Inf）；
- 截面积、容量、管道系数、泵流量非正；
- 初始水量越界（为负或超过容量）；
- 停泵水深不低于启泵水深（要求严格小于），或启泵水深高于该池最大水深；
- 泵初态与阈值不符：初态开但初始水深已低于停位，或初态关但已达到启位；
- 入流流量为负、入流时段起止非法、管道/泵引用不存在的池、管道自环、编号重复等。

## 五、HTTP API 示例

```bash
curl -X POST http://localhost:8000/api/simulate \
  -H "Content-Type: application/json" \
  -d '{
    "duration": 10800,
    "tanks": [
      {"id": "A", "bottom": 10.0, "area": 100.0, "capacity": 500.0, "initialVolume": 0.0},
      {"id": "B", "bottom": 8.0,  "area": 80.0,  "capacity": 400.0, "initialVolume": 40.0}
    ],
    "intervals": [
      {"tank": "A", "start": 0,    "end": 3600,  "flow": 0.30},
      {"tank": "A", "start": 3600, "end": 7200,  "flow": 0.02},
      {"tank": "A", "start": 7200, "end": 10800, "flow": 0.0}
    ],
    "pipes": [{"id": "P1", "from": "A", "to": "B", "coeff": 0.35}],
    "pumps": [{"id": "PU1", "tank": "B", "flow": 0.15,
               "onDepth": 3.0, "offDepth": 1.0, "initialOn": false}]
  }'
```

返回 JSON 主要字段：`times`、各池 `depth/head/volume/overflow` 曲线及 `overflow_total`、
各管 `cumulative` 累计过水量、各泵 `cumulative` 与 `switches` 切换时刻、
`summary`（`initial_storage / total_inflow / final_storage / total_pumped /
total_overflow / balance_residual`）。

## 六、项目结构

```
.
├── app/
│   ├── main.py          # FastAPI 路由、静态页托管、统一中文错误
│   ├── engine.py        # SciPy 连续时间推演引擎（事件、限流、溢流、收支）
│   ├── models.py        # 请求模型与输入校验
│   └── static/          # 原生 JS 页面（index.html / app.js / style.css）
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```
