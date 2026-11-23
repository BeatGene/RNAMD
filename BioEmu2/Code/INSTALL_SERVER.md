# BioEmu2 服务器安装指引（2026-11-12）

适用已知硬件：8 张 NVIDIA H20-3e，单卡 143771 MiB；驱动 575.57.08。
尚未核实：Linux 发行版、CPU 架构、glibc、编译器、网络与磁盘空间。
本文件是待用户在服务器执行的指引，不代表已经安装或验证成功。

## 安装选择

- 独立 Conda 环境 `bioemu2`，Python 3.12。不改现有 refinement/Protenix 环境。
- 使用官方 `cuda12` extra；当前它锁定 `torch==2.13.0+cu126`、cuEquivariance 0.11.1 CUDA 12 包。
- 不直接使用默认 `.[cuda]`：当前该 extra 使用 CUDA 13，常规驱动兼容要求为 >=580。
- `nvidia-smi` 的 CUDA 12.9 是驱动支持信息，不是环境内必须安装的 toolkit 版本。
- 不要求先安装系统 CUDA 12.9 或更新驱动。pip CUDA 依赖与现有系统 toolkit 分开处理；Triton 首次执行可能需要 C 编译器和 Python 头文件。
- 显存容量适合尝试小规模单卡验证，不保证任意长度或批量都能运行。当前全部卡都有工作负载，GPU 测试须使用实验室分配的卡。

来源：

- https://github.com/microsoft/bioemu2#installation
- https://github.com/microsoft/bioemu2/blob/main/pyproject.toml
- https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html

## 第一阶段：探测（现在执行）

在服务器创建目录：

```bash
mkdir -p "$HOME/bioemu2_setup"
```

由用户上传 `bioemu2_preflight.py` 到该目录。运行：

```bash
cd "$HOME/bioemu2_setup"
"$HOME/miniconda3/bin/python" bioemu2_preflight.py > preflight.txt 2>&1
cat preflight.txt
```

若 base Python 不在上述位置，使用已确认的 Python 3.6+ 可执行文件。
脚本仅使用标准库，不导入 torch、不占 GPU、不安装包。网络探测只请求 HTTP 头，最多约几十秒；不会下载权重或软件包。
不要把任一 HTTP 错误简单归类成“整个服务器断网”。HTTP 403/405 可能只表示访问限制；HEAD 成功也不能保证大权重下载成功。

将 `preflight.txt` 发回，再确定在线、部分离线或完整离线路线。

## 第二阶段 A：在线安装（第一阶段结果确认后执行）

以下要求 conda 软件源、GitHub、PyPI 及 PyTorch cu126 下载地址可用；HF 不通时仅权重部分改为离线上传。
先确认 `bioemu2` 环境名和 `$HOME/Code/BioEmu2` 尚未使用；如果已经存在，先核实内容，不覆盖。

```bash
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda env list
```

确认目标名称未使用后：

```bash
conda create -n bioemu2 python=3.12 pip -y
conda activate bioemu2
python --version
python -m pip install --upgrade pip setuptools wheel
mkdir -p "$HOME/Code"
git clone --depth 1 https://github.com/microsoft/bioemu2.git "$HOME/Code/BioEmu2"
cd "$HOME/Code/BioEmu2"
git rev-parse HEAD > "$HOME/bioemu2_setup/source_commit.txt"
python -m pip install '.[cuda12]' --extra-index-url https://download.pytorch.org/whl/cu126
```

如果下载报错，保留完整错误；不要用 `--no-deps`、改装默认 CUDA 13 包、降到旧训练环境的 torch，或关闭 TLS 验证来绕过。
这组版本来自本次核对的官方 main；若以后源码依赖发生变化，应以记录的源码及其 pyproject.toml 重新核对。

安装后先做 CPU/依赖检查：

```bash
python -m pip check
python -m pip show bioemu2 torch cuequivariance cuequivariance-torch cuequivariance-ops-torch-cu12 cuequivariance-ops-cu12
python -c 'import torch; from bioemu2 import System, EmuSession, load_model; print("torch:", torch.__version__); print("torch CUDA:", torch.version.cuda); print("BioEmu2 imports OK")'
bioemu2 --help
bioemu2 propagate --help
python -m pip freeze > "$HOME/bioemu2_setup/installed_packages.txt"
```

这些检查不加载模型或执行 GPU 推理。`--help` 和 import 成功仅代表软件层检查通过，不能代替 CUDA 内核与真实传播验证。

## 模型文件：在线下载或离线上传

首次推理需要 `bioemu2-preview` 的 checkpoint 和同目录的 config.yaml。
软件包安装成功不表示权重已经下载。

官方仓库相对路径：

```text
checkpoints/bioemu2-preview/checkpoint.ckpt
checkpoints/bioemu2-preview/config.yaml
```

在线服务器可在已激活的 `bioemu2` 环境中运行：

```bash
python - <<'PY'
from pathlib import Path
from huggingface_hub import hf_hub_download

root = Path.home() / 'bioemu2_data'
for filename in ('checkpoint.ckpt', 'config.yaml'):
    path = hf_hub_download(
        repo_id='microsoft/bioemu2',
        filename=f'checkpoints/bioemu2-preview/{filename}',
        local_dir=root,
    )
    print(path)
PY
```

如果服务器只能下载 pip 包、无法下载 HF 权重，在联网电脑下载这两个文件后由用户上传，保持如下布局：

```text
~/bioemu2_data/checkpoints/bioemu2-preview/checkpoint.ckpt
~/bioemu2_data/checkpoints/bioemu2-preview/config.yaml
```

后续通过 `--checkpoint-path` / `load_model(checkpoint_path=...)` 指定本地文件，不依赖 HF 自动下载。
源码：https://github.com/microsoft/bioemu2/blob/main/src/bioemu2/checkpoints.py
文档：https://github.com/microsoft/bioemu2/blob/main/docs/checkpoints.md

## 第二阶段 B：完整离线安装

必须先读取服务器探测报告，再准备匹配 Linux 架构、glibc 和 Python 3.12 的包。
不能把当前 Mac 上直接下载的默认 pip wheel 或打包的 Mac Conda 环境上传给 Linux 使用。

优先方案：在兼容的联网 Linux 主机上建立并检查 `bioemu2` 环境，记录源码 commit 和依赖版本，然后用 conda-pack 打包；传到服务器解压、执行 conda-unpack 后再验证。构建机通常不需要 GPU 即可准备包，但只有目标服务器能完成 H20/CUDA 运行验证。是否能使用该方案取决于用户是否有联网 Linux 主机或 Linux 容器。

替代方案：准备匹配服务器平台的 Python 3.12 Conda 包与完整 wheelhouse，在目标机使用本地索引安装。需要额外核对所有传递依赖和 wheel 平台标签，不能只上传源码压缩包或 requirements.txt。

离线交付至少包括：

1. 匹配 Linux 的完整 Conda 环境包，或 Python/Conda 包与完整 wheelhouse。
2. 安装所用源码快照及 commit 记录（环境包内可已包含安装后的软件）。
3. 配套 checkpoint.ckpt 和 config.yaml。
4. 后续传播使用的本地体系定义、完整起始 CIF，以及对应校验信息。

纯 RNA/DNA 体系不要求蛋白 A3M；用本地 YAML/CIF 可避免 PDB 在线下载。核酸不需要沿用 Protenix 的 MSA 数据库。
仍需在离线条件下实测标准 RNA 体系准备及传播，确认该源码版本没有额外未缓存资源请求。
MSA 文档：https://github.com/microsoft/bioemu2/blob/main/docs/msa.md

## 第三阶段：GPU 与传播验收

等用户提供探测/安装结果，以及可用于验证的 GPU 编号后，再执行：

1. CUDA 张量和 cuEquivariance 实际算子检查。
2. 从本地 checkpoint 加载模型，确认 supports_propagation。
3. 一个很短的标准 RNA、单样本、固定种子的生成与传播检查。
4. 一个项目真实 decoy 的原子映射与传播检查。

这之前不启动长链批量任务。当前“8 张卡都有占用”不能解释为 8 张都可用；显存空余也不代表没有其他任务占用计算资源。

## 本轮文件和清理

- `bioemu2_preflight.py`：服务器探测脚本；安装验收完成后可删除，不参与训练。
- `INSTALL_SERVER.md`：安装指引；可删除，建议保留作为操作记录。
- 服务器运行产生的 `preflight.txt`：诊断报告；问题解决后可删除。
- 若按在线步骤执行，还会生成 `source_commit.txt` 和 `installed_packages.txt`：建议保留以便复现。
- 安装的 Conda 环境、源码和模型权重是后续运行资源，不属于探测临时文件。
