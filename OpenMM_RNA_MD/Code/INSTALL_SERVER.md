# OpenMM + OL3 RNA：服务器环境准备

更新（2026-11-17）：已收到服务器报告，Linux x86_64 / glibc 2.36 / 驱动 575.57.08。
下一步以 [OFFLINE_STEPS.md](OFFLINE_STEPS.md) 的离线构建与安装命令为准。
本节以下保留首次探测流程；代码目录现在共 10 个文件，首次准备包中的 6 个仍可保留。

第一步只运行探测。用户通过 SSH 上传并执行；本地助手不登录服务器。
目标为独立 Conda 环境：Python 3.11、OpenMM 8.x、AmberTools 24–26、ParmEd 4、MDTraj、NumPy。
OL3、水/离子参数随软件提供，无需模型权重。环境版本范围是求解要求，成功安装后保存精确版本和构建号。

## 1. 上传与探测（现在执行）

本地目录：`RNAMD/OpenMM_RNA_MD/Code/`。上传整个目录的 6 个文件到服务器
`~/openmm_rna_setup/code/`，也可以上传同级生成的 `openmm_rna_setup_code.tar.gz`。
使用已连接 SSH 软件的文件传输功能即可，不需要再提供账号、密码或私钥。

压缩包上传到服务器 `~/` 后执行：

```bash
mkdir -p "$HOME/openmm_rna_setup/code"
tar -xzf "$HOME/openmm_rna_setup_code.tar.gz" -C "$HOME/openmm_rna_setup/code"
cd "$HOME/openmm_rna_setup/code"
bash probe_server.sh
```

若同时上传 `.tar.gz.sha256` 校验文件，可先在服务器 `~/` 运行
`sha256sum -c openmm_rna_setup_code.tar.gz.sha256` 再解压。

直接上传文件则跳过解压。脚本不需要 chmod，也不安装包、不运行 GPU 计算、不修改 Conda 配置。
探测：OS/CPU 架构、glibc、GPU 驱动与显存、Conda 路径/虚拟包、已有环境中的 MD 包、
输出目录所在磁盘剩余空间、Conda-forge 两个索引和 PyPI 的 HTTPS 可达性。
网络只读取小量响应；不会关闭 TLS 校验。并发探测有超时；网络失败也会保存报告。
不读取 `.condarc`、SSH 密钥或项目 API key，不导出完整环境变量。

将终端输出和报告目录中的 `report.json` 发回。`summary.txt` 也是同一份摘要。
如果 GPU 查询失败，请在实验室允许使用的 GPU 计算节点/分配的交互任务内再运行；登录节点的失败不能代表整个集群无 GPU。
网络成功仅说明索引 URL 可达，不保证所有依赖包下载成功。`nvidia-smi` 的驱动能力与当前环境的 CUDA runtime 是不同信息。

## 2. 在线分支（读完探测报告后再确定 CUDA_VERSION）

安装脚本只创建指定的新 prefix，已有路径会拒绝覆盖；不更新 base，不装 PyTorch，不改驱动。
它使用单次命令的 conda-forge/strict 配置，安装失败保留日志和部分环境供诊断，不自动删除重试。
CUDA_VERSION 由实际驱动及 Conda 可用构建确定；不在未知驱动上直接硬编码最新 CUDA。

以下占位符必须先替换，暂时不要照抄执行：

```bash
cd "$HOME/openmm_rna_setup/code"
bash install_online.sh "$HOME/conda-envs/openmm_rna_ol3" '替换为确定的CUDA版本'
```

长时间安装可使用实验室已有的 tmux 会话；或在确定参数后：

```bash
cd "$HOME/openmm_rna_setup/code"
nohup bash install_online.sh "$HOME/conda-envs/openmm_rna_ol3" '替换为确定的CUDA版本' \
  > "$HOME/openmm_rna_setup/install_console.log" 2>&1 < /dev/null &
```

`RNA_MD_ENV_INSTALLED_INVENTORY_OK` 只表示导入和文件检查成功，尚未证明 CPU/CUDA 运行成功。
安装日志中另有 `conda-explicit.txt`、`environment-resolved.yml` 和检查报告。

## 3. 离线分支（报告确认后准备对应包）

若不能联网，先根据报告检查已有环境/缓存是否能复用；否则在能联网的、目标兼容的 Linux
环境里解算并打包完整 Conda 环境，再上传、校验 SHA256、解包到新 prefix、运行 conda-unpack。
不能直接打包 macOS 的 Conda 环境给 Linux 使用。
首次准备时没有生成完整依赖离线包。现在架构、glibc、驱动已知，新增离线构建脚本，
详见 OFFLINE_STEPS.md；Conda 查询超时，因此缓存状态仍未知。
本压缩包仅包含准备脚本，不包含 Conda 包或 CUDA 库。离线时不要运行在线安装脚本反复重试。

## 4. 安装后的验收

环境创建后用 prefix 激活（不依赖 Conda 安装在 miniconda3 还是 anaconda3）：

```bash
conda activate "$HOME/conda-envs/openmm_rna_ol3"
unset PYTHONPATH PYTHONHOME
cd "$HOME/openmm_rna_setup/code"
python check_environment.py --platform CPU
```

CPU 验收：用 tleap 的 OL3 + TIP3P 构建合成 12 nt RNA，加水和中和 Na+，检查电荷，
保存 Amber 拓扑/坐标，再用 OpenMM 的 CPU 平台最小化并运行 20 步（1 fs/步），检查能量和坐标有限。
并检查 cpptraj 可执行文件及 ParmEd/MDTraj 导入。该合成 RNA 不来自训练/验证/测试数据。

CPU 成功后，在获准的 GPU 节点上验收 CUDA：

```bash
RNA_MD_GPU='替换为你获准使用的一张GPU编号或UUID'
CUDA_VISIBLE_DEVICES="$RNA_MD_GPU" python check_environment.py --platform CUDA
```

如果调度器已经限制 CUDA_VISIBLE_DEVICES，必须遵守已有分配；只暴露其中一张获准 GPU。
脚本在所选可见 GPU 上使用 DeviceIndex=0 与 mixed 精度，不自动挑空闲卡，不会回退 CPU 并宣称 CUDA 通过。
OpenMM 的 mixed 精度不是训练模型的 BF16 设置。

成功标志依次为 `RNA_MD_CPU_OK`、`RNA_MD_CUDA_OK`；每次独立目录保留 tleap 日志、
拓扑/坐标及 `report.json`。失败也尽可能保存 traceback 和阶段。
这只验收软件链路，20 fs 不代表真实靶标平衡、采样充分、吞吐或生物学正确性。
生产体系、结构化扰动、PT 映射/置信度协议将在环境通过后准备。

## 文件及清理

本轮新增 6 个代码/说明文件，以及代码传输压缩包；不参与训练，完成环境验收后均可删除，建议保留复现。
探测只新增 `~/openmm_rna_setup/probes/` 内的报告；可删除。
安装会新增指定 Conda 环境、Conda 下载缓存和安装日志；验收产生合成 RNA 文件。
日志/合成文件可在保存结果后删除，正式环境需要保留才能运行后续 MD。
本地没有安装 MD 软件，没有服务器执行结果，未修改原训练或 BioEmu2/DynaRNA 环境。
本地已检查 Python/Bash 语法、探测报告生成及断网报告、安装器拒绝覆盖已有路径、
无效 CUDA 参数拒绝，以及依赖缺失时验收返回失败并保留报告；尚未实际完成 Conda 解算或 CPU/CUDA RNA 运行。

## 官方依据

- OpenMM 安装与 CUDA：https://docs.openmm.org/latest/userguide/application/01_getting_started.html
- OpenMM 的 Amber 文件与 OL3：https://docs.openmm.org/latest/userguide/application/02_running_sims.html
- AmberTools：https://ambermd.org/AmberTools.php
- conda-forge AmberTools：https://github.com/conda-forge/ambertools-feedstock
- OL3 参数说明：https://kfc.upol.cz/ff_ol/refinements.php
- 离线迁移工具：https://conda.github.io/conda-pack/
