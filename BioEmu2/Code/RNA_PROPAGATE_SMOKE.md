# 短 RNA 真实 Propagate 验收（2026-11-13）

这是待用户在实验室服务器执行的测试，尚未宣称运行成功。使用已安装的 BioEmu2、现有本地 checkpoint、单张用户获准使用的 GPU；不安装依赖、不下载 PDB/MSA/权重、不改动训练数据。

合成 RNA 为 `GGGCGAAAGCCC`（12 nt）。先从 equilibrium 模式生成一个起始构象，保存并重新读取/映射起始 CIF，再运行真实 `EmuSession.propagate(..., lag_time_ns=1.0)`，得到一个终点。使用原始采样器默认设置，不用随机坐标或伪造输出代替模型。

## 用户上传两个文件

本地目录：`/Users/fudanxth/Learning/Laboratory/Admis/graduate_first/RNAMD/BioEmu2/Code/`。

- smoke_propagate_rna.py
- run_rna_propagate_smoke.sh

上传到服务器同一目录 `~/bioemu2_setup/propagate_smoke_code/`。本说明无需上传。

## 服务器后台启动

先确认安装检查已通过，并使用上一步模型加载验证成功时的同一张获准 GPU。以下变量必须填写真实编号，不自动挑选空闲显存最大的卡：

```bash
cd "$HOME/bioemu2_setup/propagate_smoke_code"
BIOEMU2_GPU='填写获准使用的GPU编号'
bash run_rna_propagate_smoke.sh "$BIOEMU2_GPU"
```

默认环境 `$HOME/miniconda3/envs/bioemu2`；若使用其他前缀，作为第二个参数传入。脚本直接调用该环境 Python 并设置 PATH，不依赖当前 shell 是否激活 Protenix/BioEmu2。后台进程脱离终端输入输出，普通 SSH 断开后仍可运行；平台回收容器/节点会影响任务存活。

首次运行可能导入较多文件并编译 GPU 内核；NFS 上的环境和权重读取仍可能耗时。每个主要阶段都会打印 START/OK 与耗时。编译缓存默认放在用户专属 `/var/tmp/bioemu2-smoke-UID`，避免在慢 NFS 上写入大量编译临时文件。

日志和结果路径自动生成，不覆盖旧结果；默认根目录 `~/bioemu2_setup/propagate_smoke/`。查看最新任务：

```bash
BIOEMU2_RUN="$(cat "$HOME/bioemu2_setup/propagate_smoke/latest_run_path.txt")"
tail -f "$BIOEMU2_RUN/run.log"
```

Ctrl+C 只退出日志查看。完整成功标志：

```text
RNA_PROPAGATE_SMOKE_OK
SMOKE_EXIT_CODE=0
```

成功或失败均尝试写 `results/report.json`，记录版本、GPU、种子、阶段耗时及失败位置。新任务若在解析参数/创建输出目录前即失败，可能只有 run.log。

## 产物与判读

```text
run_时间戳_随机后缀/
  run.log
  run.pid
  env_prefix.txt
  results/
    report.json
    system.yaml
    start/topology.cif
    start/samples.xtc
    propagated/topology.cif
    propagated/samples.xtc
```

验证内容：真实 GPU 模型执行、生成与传播接口、起始 CIF 原子映射、帧/原子/残基数、坐标有限性、保存后的 XTC/CIF 读取及坐标/原子顺序一致性。CIF 和 XTC 的舍入误差分别采用适合其格式的容差。MDTraj 坐标以 nm 表示，报告中的位移距离转换为 Å。

`start_to_endpoint_aligned_rmsd_A` 只描述生成起点与传播终点的差异，不是相对实验 native 的误差。1 ns 是模型传播的时间间隔，不是程序实际耗时；只生成终点，不产生每个中间时刻的轨迹。

通过仅说明短 RNA 的软件流程可运行，不证明构象物理合理、动力学准确或长链可用。本测试未执行 RNA 物理性检查；官方内置 physicality 目前不覆盖核酸。后续应再用 train 集中真实 Protenix decoy 验证映射，并单独做 RNA 几何 QC。

请返回 run.log 末尾和 results/report.json。失败时保留该任务目录，提供完整 traceback，不反复启动任务覆盖现场。

## 文件清理

本轮新增的两个脚本和本说明，完成验收后均可删除，建议保留复现。服务器会新增日志、报告、system.yaml、两组 CIF/XTC 和用户专属编译缓存；这些均为测试产物，不参与训练，可在记录验收结果后删除。不要误删正式环境、已有模型权重或其他任务的编译缓存。

官方依据：
- https://github.com/microsoft/bioemu2/blob/main/docs/propagation.md
- https://github.com/microsoft/bioemu2/blob/main/docs/checkpoints.md
- https://github.com/microsoft/bioemu2/blob/main/docs/msa.md
- https://github.com/microsoft/bioemu2/blob/main/docs/sampling.md#check-physicality
