# dl-gpu-monitor-lite

[![Version](https://img.shields.io/badge/version-0.1.0-blue)]()
[![Python](https://img.shields.io/badge/Python-3.8%2B-green)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

深度学习训练用的轻量 GPU 小监视器：实时曲线 + 任务列表 + 多卡总览。单文件、零依赖。

## 问题

深度学习训练时，Windows 自带的监控手段普遍不顺手：

| 工具 | 实时曲线 | 进程级显存 | 多卡总览 | HTTP API | 安装成本 |
|---|---|---|---|---|---|
| 任务管理器 | ✗（仅当前值） | 模糊（按引擎） | ✗ | ✗ | 自带 |
| `nvidia-smi` | ✗ | ✓ | ✓ | ✗（文本轮询） | 驱动自带 |
| GPU-Z / HWiNFO / Afterburner | ✓ | ✗ | 弱 | ✗ | 装全家桶 |
| **dl-gpu-monitor-lite** | **✓** | **✓** | **✓（按需出现）** | **✓** | **零（一个 .py）** |

要点：任务管理器看不到温度/功耗/单进程显存；社区工具要么重（常驻图形程序 +
驱动级传感器全家桶），要么只有进程列表没有曲线。训练时最需要的"曲线 + 任务数"
两个信息，恰好没有轻量方案同时提供。

## 方案

1. **零依赖采样**：每秒调用驱动自带的 `nvidia-smi`（NVML 命令行），无 pip 包、
   无 CDN、无常驻图形程序。整个工具就是一个 `gpu_monitor.py`（约 400 行，
   Python 标准库）。
2. **自带 HTTP API**：`GET /api/state` 返回 JSON——逐卡指标历史 + 进程归属，
   可接自己的面板/脚本/告警。
3. **多卡自适应**：检测到多块 GPU 才显示"多卡总览"（每卡当前状态 + 利用率迷你
   走势图 + 该卡任务数）与 GPU 切换标签；单卡时界面保持极简，不出现多卡元素。
4. **纯手绘 SVG 图表**：不引入图表库，页面离线可用；横轴带时间标尺（HH:MM:SS）。

实测（本机 RTX 5070 Ti，空闲态）：页面 HTML 约 11KB，Python 进程常驻内存
<30MB，单次采样 <50ms，不影响训练。

### 数据来源

- 逐卡指标：`nvidia-smi --query-gpu=index,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw --format=csv,noheader,nounits`
- 进程归属：`--query-compute-apps=pid,process_name,used_memory,gpu_uuid` 配合
  `index,uuid` 映射，把进程精确归属到具体某块卡。

## 安装

```sh
# Windows（Python 3.8+，训练环境一般自带）
python gpu_monitor.py          # 自动打开浏览器
# 或直接双击 start_gpu_monitor.bat
```

访问 http://127.0.0.1:8770 即用。无需 `pip install`，无需安装驱动以外的任何东西。

> 端口被占用时修改 `gpu_monitor.py` 顶部 `PORT = 8770`。

## API

`GET /api/state`：

| 字段 | 说明 |
|---|---|
| `gpuNames` / `gpuCount` | 每块 GPU 名称与数量 |
| `history` | 每秒一点的逐卡指标（util/memUsed/memTotal/temp/power），保留最近 15 分钟 |
| `processes` | 当前 GPU 计算进程：pid / name / memMiB / gpuIndex |

```sh
curl http://127.0.0.1:8770/api/state
```

## 验证

- 单卡/多卡双模式冒烟测试（桩 DOM + 伪造双卡数据）：总览卡片、每卡任务徽标、
  GPU 切换、任务表 GPU 归属列 —— 全部断言通过
- 页面 JS 经 Node 编译检查，Python 语法检查通过
- 本机实测：RTX 5070 Ti 指标与进程查询正常（含 `gpu_uuid` 归属）

## 局限

- 仅支持 NVIDIA GPU（数据源是 NVML/nvidia-smi；AMD 可用 LibreHardwareMonitor
  类工具替代）。
- 任务列表只统计 `compute-apps`（CUDA 计算进程），纯显存占用不计算的行为不计入。
- 历史保留 15 分钟、单进程内存窗口：重启即清零，不做持久化。
- 面向 Windows 使用（附带 .bat 启动器）；核心逻辑仅依赖 nvidia-smi，Linux 下
  同样可跑，但未针对测试。
