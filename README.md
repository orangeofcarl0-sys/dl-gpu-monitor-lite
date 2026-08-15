# GPU 监测 (gpu-monitor)

轻量级 Windows GPU 监控小工具：**实时曲线 + 任务列表 + 多卡总览**。
单文件、零第三方依赖，浏览器界面，开箱即用。

## 功能

- **实时曲线**：利用率 / 显存 / 温度 / 功耗 四条曲线，1 秒刷新，保留最近 15 分钟，横轴带时间标尺（HH:MM:SS）
- **任务列表**：当前 GPU 上运行的进程数量、PID、进程名、显存占用 —— 数据来自驱动层 `nvidia-smi`，比任务管理器准确
- **多卡支持**：检测到多块 GPU 时自动出现"多卡总览"（每卡当前状态 + 利用率迷你走势图 + 该卡任务数徽标）和 GPU 切换标签；单卡时界面保持简洁，多卡功能不显式出现
- **零依赖**：仅 Python 标准库 + NVIDIA 驱动自带的 `nvidia-smi`，无需 `pip install`，无 CDN，完全离线可用
- **自带 HTTP API**：`/api/state` 返回 JSON，方便二次开发接入自己的面板

## 快速开始

1. 安装 Python 3.8+（训练环境一般自带）
2. 双击 `start_gpu_monitor.bat`，或命令行运行 `python gpu_monitor.py`
3. 浏览器自动打开 http://127.0.0.1:8770

> 界面预览：深色主题仪表盘 —— 顶部为当前值卡片（利用率/显存/温度/功耗），中部为四条实时曲线，底部为 GPU 任务列表；多卡机器上还会显示每卡总览卡片与 GPU 切换标签。

## HTTP API

`GET /api/state` 返回 JSON：

| 字段 | 说明 |
|---|---|
| `gpuNames` | 每块 GPU 的名称 |
| `gpuCount` | GPU 数量 |
| `history` | 每秒一点的逐卡指标（util/memUsed/memTotal/temp/power），保留最近 15 分钟 |
| `processes` | 当前 GPU 计算进程：pid / name / memMiB / gpuIndex |

```bash
curl http://127.0.0.1:8770/api/state
```

## 工作原理

每 1 秒调用一次驱动自带的 `nvidia-smi`：

- 逐卡指标：`--query-gpu=index,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw`
- 进程归属：`--query-compute-apps=pid,process_name,used_memory,gpu_uuid` + `index,uuid` 映射

前端为纯静态 HTML + SVG（手绘图表），无任何外部资源依赖。

## 常见问题

- **页面提示无数据**：确认 NVIDIA 驱动已安装（`nvidia-smi` 能输出）；多 GPU 服务器请确保驱动支持 `gpu_uuid` 查询
- **任务列表为空但明明在训练**：`compute-apps` 只统计 CUDA 计算进程，纯显示/拷贝类进程不计入
- **端口被占用**：修改 `gpu_monitor.py` 顶部的 `PORT = 8770`
- **浏览器未自动打开**：手动访问 http://127.0.0.1:8770

## 许可证

[MIT](LICENSE)
