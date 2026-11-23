# DynaRNA 离线安装：Mac 构建，实验室服务器运行

服务器预检已确认：Debian 12，Linux x86_64，glibc 2.36，H20-3e，驱动 575.57.08。2026-11-12 的小型网络请求均未成功，因此采用离线传输。conda info 超时不等于 conda 环境损坏，本方案不依赖服务器求解或下载依赖。

当前状态（2026-11-12 更新）：用户构建日志已确认 Python 3.10.22、PyTorch 2.2.2+cu121、NumPy 1.23.5 环境中的官方模块导入、权重严格加载和 CPU 一步反向采样通过。原打包阶段因 Miniforge base 的 Python 3.14 中缺失 pkg_resources 失败；脚本现改为独立的 Python 3.10 venv 运行 conda-pack 0.9.2，并在打包前验证其导入和 CLI。修复后的打包、迁移、GPU和完整推理仍待执行。只有构建脚本成功退出且显示 BUILD COMPLETE 才得到可上传包。

## 1. 在 Mac 上构建 Linux 环境包

打开 Docker Desktop，确认 Docker Engine 正在运行。在 Mac 终端运行：

```bash
bash "/Users/fudanxth/Learning/Laboratory/Admis/graduate_first/RNAMD/DynaRNA/Code/prepare_offline_macos.sh"
```

脚本通过 `linux/amd64` 容器构建，不使用 Mac 的 conda 环境，不接触服务器。需要 Mac 上 Docker 网络能访问 GitHub、conda-forge、PyPI、PyTorch 和 Zenodo；如果之前 BioEmu2 使用了 Docker 网络设置，保留那些设置即可。

候选环境为 Python 3.10、PyTorch 2.2.2 CUDA 12.1、NumPy 1.23.5 等，具体见 requirements-inference.txt。CUDA 版 PyTorch 的版本号在安装后应含 cu121。此环境独立于 Protenix 和 BioEmu2。驱动支持的 CUDA 上限不是强制安装版本，本方案不升级服务器驱动。

构建会：固定并记录 GitHub commit；按发布 SHA256 检查 Linux Miniforge 安装器；按 Zenodo 发布 checksum 检查 DynaRNA.pkl；下载源码；创建环境；安装依赖；检查 pip 依赖一致性；在 CPU 上严格加载权重并通过官方采样器执行一个合成反向步骤；用隔离的 conda-pack 0.9.2 打包；生成逐文件与外层 SHA256。打包工具位于容器 /opt/dynarna-pack-tools，不进入运行环境，也不对 Miniforge base 的 setuptools 做降级。

首次下载和 x86 仿真可能较慢，CUDA 包会占用数 GB 以上磁盘。不要关闭终端。构建输出保存在本项目 Offline/时间戳_进程号/，失败也保留容器、已完成下载和 build.log。

如果失败，把 build.log 末尾错误发回对话。修复脚本后可以用屏幕显示的真实容器名继续：

```bash
docker start -a dynarna-offline-实际时间戳和进程号
```

这个命令中的容器名必须替换；不要重复运行 prepare 脚本创建另一个容器来续传原下载。已有容器通过只读挂载读取本机 Code 目录，因此会使用更新后的构建脚本；重启会重新检查各阶段，已安装的 DynaRNA 环境不会重新创建，完整且校验通过的下载会复用。部分未完成文件可能重新下载。原 build.log 不会自动记录这次 docker start 的输出，如需保存可用 tee 写入新的 resume 日志。

本次已知容器可直接在 Mac 终端恢复：

```bash
docker start -a dynarna-offline-20261112_190724_53423
```

最终完成行包含两个需要上传的文件：

```text
dynarna_offline_bundle.tar
dynarna_offline_bundle.tar.sha256
```

## 2. 上传服务器并安装

将上述两个文件上传到现有的 `~/Code/DynaRNA_install/`。在服务器运行：

```bash
cd "$HOME/Code/DynaRNA_install"
sha256sum -c dynarna_offline_bundle.tar.sha256
```

只有校验显示 OK 才继续解压。应使用尚不存在的 bundle 目录；若已有同名目录，请换一个空目录解压，避免与旧包混合。

```bash
tar -xf dynarna_offline_bundle.tar
bash bundle/install_offline_server.sh
```

默认新建：

- 环境：`~/miniconda3/envs/dynarna`
- 源码：`~/Code/DynaRNA`
- 权重：`~/Code/DynaRNA/ckpt/DynaRNA.pkl`

安装器会验证包内全部 SHA256；拒绝覆盖已有环境或源码目录；使用新环境自带 Python 运行 conda-unpack；不调用 pip、conda solve 或下载。随后进行 CPU 模型检查。

若默认目标已经存在，请指定两个新的绝对路径，例如：

```bash
bash bundle/install_offline_server.sh   "$HOME/miniconda3/envs/dynarna_v2"   "$HOME/Code/DynaRNA_v2"
```

使用自定义路径时，同步修改下文全部路径。失败留下的半安装目录也不会被自动删除或覆盖。

## SSH 断开后的后台安装

无需重新构建或重新传输离线包。先重新登录服务器。将本机新增 `start_install_background.sh` 单独上传到 `~/Code/DynaRNA_install/`，与 `bundle` 目录并列，不能放入 bundle 改动已校验清单中的文件。

```bash
cd "$HOME/Code/DynaRNA_install"
bash start_install_background.sh
```

脚本按安装 bundle、目标环境和源码路径检查本用户的进程参数及工作目录，并用 flock 防止自身重复启动；不会仅凭 install_offline_server.sh 或 sha256sum 的进程名就阻止安装，避免把并行的 BioEmu2 安装误认成 DynaRNA。如检测到这些 DynaRNA 路径仍在使用，只显示相关进程，不启动新任务。不能将原来仍运行的进程事后转换成 nohup；先保留它，确认状态。

若旧进程已退出，脚本使用 nohup 后台启动原安装器，标准输入为 /dev/null，输出写日志。已有环境或源码目录时，会保留原目录，改用带 `_recover_时间戳_进程号` 后缀的新目录；这是从现有离线包重新安装，不是从压缩流断点继续。

如果已确认现有安装未完成，希望继续使用原环境名 dynarna 和原源码路径，上传最新版启动脚本后运行：

```bash
cd "$HOME/Code/DynaRNA_install"
bash start_install_background.sh --reuse-names
```

该选项在进程检查通过后，把已有目标目录改名为同级的 `.interrupted_时间戳_进程号` 备份，再后台安装到原路径。它不会删除旧目录；备份只用于保留中断状态，不能假定改名后可激活使用。备份映射保存在该次日志目录的 backups.txt。包内校验仍会重新执行，CPU 检查通过后才能继续 GPU 验证。

终端会打印实际环境、源码、日志目录，以及可直接复制的 tail 命令。日志在 `~/Code/DynaRNA_install/install_logs/时间戳_进程号/install.log`；`paths.txt` 记录实际路径，`install.pid` 记录后台进程，结束后 `exit_code.txt` 记录退出码。0 表示离线安装和 CPU 检查通过。没有 exit_code.txt 不一定表示仍运行：若容器或服务被强制终止，还需检查 PID 和日志。不要仅凭启动成功判定安装成功。

用 tail -f 看日志时按 Ctrl+C 只停止查看，不停止后台安装。后续 GPU 和采样命令中的环境、源码路径必须按 paths.txt 修改。保留旧的部分安装目录，待新安装验证通过后再决定是否清理。

新脚本只负责启动和日志，不进入运行环境；完成安装并保存记录后可删除。

## 3. 在选定 GPU 上检查

先查看当时 GPU 占用，并按实验室资源安排选择可用卡：

```bash
nvidia-smi
```

下面假设你选择了 GPU 5。这里的 5 仅为示例，不依据旧截图认定它可以独占。

```bash
conda activate "$HOME/miniconda3/envs/dynarna"
CUDA_VISIBLE_DEVICES=5 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2   python "$HOME/Code/DynaRNA/install_helpers/check_installation.py"   --source "$HOME/Code/DynaRNA"   --checkpoint "$HOME/Code/DynaRNA/ckpt/DynaRNA.pkl"   --device cuda
```

若 conda activate 仍超时，可以直接把上面的 python 换成 `"$HOME/miniconda3/envs/dynarna/bin/python"`；不依赖当前 Protenix 环境的 Python。

通过标准：CUDA 运算成功；官方模块可导入；权重严格加载；官方采样器一个反向步骤输出正确形状且全部数值有限；最后打印 PASS。一个合成步骤仅检查安装和运行兼容性，不证明800步采样质量。

## 4. 用官方 AAAA 例子生成两条 C4′ 结构

只在 GPU 检查通过后执行。输出目录必须尚不存在；重复运行时换一个新名字。

```bash
CUDA_VISIBLE_DEVICES=5 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2   "$HOME/miniconda3/envs/dynarna/bin/python"   "$HOME/Code/DynaRNA/install_helpers/run_official_inference.py"   --source "$HOME/Code/DynaRNA"   --checkpoint "$HOME/Code/DynaRNA/ckpt/DynaRNA.pkl"   --input "$HOME/Code/DynaRNA/AAAA.pdb"   --output "$HOME/Code/DynaRNA/smoke_AAAA_001"   --num-samples 2 --steps 800 --seed 0
```

入口包装器在内存中替换原推理脚本的运行参数、随机种子和自动选卡逻辑，并移除未使用的 analysis 可视化导入，避免额外安装 notebook 依赖；不改源码文件、模型结构、采样算法或坐标缩放。它固定checkpoint路径，拒绝覆盖输出，并检查输出C4′数量和有限数值。若官方源码入口结构变化，参数检查会报错，而非静默套用。

先把构建日志、GPU检查输出和两条输出结构带回本地再判断安装是否完成。尚未安装 Arena；C4′结果不能直接作为当前重原子 refinement 的训练输入。全原子重建和结构质量检查在本步骤通过后再做。

## 文件用途与删除

- `server_preflight.py`：前一步服务器检查；已完成后可以删除。
- `prepare_offline_macos.sh`：Mac 构建入口；安装完成并保存记录后可以删除。
- `build_in_container.sh`、`download_assets.py`、`requirements-inference.txt`：Linux环境构建与版本记录；保存可复现记录后可以删除。
- `install_offline_server.sh`：服务器离线安装器；安装完成后可以删除。
- `check_installation.py`：安装验证；建议保留，正常采样不依赖它。
- `run_official_inference.py`：参数化推理入口；使用此命令采样时需要保留服务器副本。
- 本说明：不参与运行，可以删除。
- `Offline/` 下的构建缓存、容器和传输包：确认服务器环境、源码、权重完整且验证成功后再清理。不要误删服务器已解包的环境、源码和权重。

当前没有修改 RNA 项目、Protenix环境或已有训练数据。

## 来源

- [DynaRNA 官方仓库](https://github.com/lizxSJTU/DynaRNA)
- [官方环境文件](https://github.com/lizxSJTU/DynaRNA/blob/main/DynaRNA.yml)
- [官方推理入口](https://github.com/lizxSJTU/DynaRNA/blob/main/infer_DynaRNA.py)
- [官方模型记录](https://zenodo.org/records/15600148)
- [PyTorch 历史版本安装说明](https://pytorch.org/get-started/previous-versions/)
- [Miniforge 固定版本](https://github.com/conda-forge/miniforge/releases/tag/26.9.4-2)
- [conda-pack 0.9.2 源码：使用 importlib.resources](https://github.com/conda/conda-pack/blob/0.9.2/conda_pack/core.py)
- [setuptools 对 pkg_resources 的移除说明](https://setuptools.pypa.io/en/stable/deprecated/pkg_resources.html)
