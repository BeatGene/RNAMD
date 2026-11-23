# 针对 2026-11-17 服务器报告的离线环境

已知：Linux x86_64，glibc 2.36，H20-3e，驱动 575.57.08，系统 nvcc 12.6。
目标：Python 3.11 + OpenMM 8.x + AmberTools 24–26 + OL3/TIP3P + ParmEd 4 + MDTraj + CUDA runtime 12.6。
范围要求由 conda-forge 解算，精确构建记录随包提供。驱动支持 CUDA 12.6，不需要更改服务器驱动。
Conda/HTTPS 子进程超时可能受到网络、Conda 插件或共享盘冷启动影响；目前仅能说未验证连网，不能断言无网络或没有缓存。

## 本地 Mac：先构建，不用上传这批脚本到服务器

打开 Docker Desktop，等引擎启动。在 Mac 终端运行：

```bash
cd /Users/fudanxth/Learning/Laboratory/Admis/graduate_first/RNAMD/OpenMM_RNA_MD/Code
bash prepare_offline_macos.sh
```

这个脚本在 Debian bookworm（glibc 2.36）的 linux/amd64 容器内构建 Linux 环境，
不是打包 macOS 环境。Apple Silicon 上模拟 x86 可能较慢；下载、解算、CPU RNA 检查没有固定完成时间。
容器没有 GPU；仅在构建容器设置 CONDA_OVERRIDE_CUDA=12.6 让解算器选择目标 CUDA 包，服务器不使用此覆盖。
不安装宿主 Mac 的 Python/Conda 包，不启动特权容器，不挂载 Docker socket，不改原训练或 BioEmu2 环境。

构建保留在 `OpenMM_RNA_MD/Offline/时间戳_PID/`，终端显示完整路径。
成功必须出现 `RNA_MD_OFFLINE_BUNDLE_CPU_OK`。它要求实际打包、解包到新路径、conda-unpack，
并在迁移后的环境上完成 tleap→OL3/TIP3P→OpenMM CPU RNA 短运行；缺失依赖/失败不会继续宣称完成。
也检查 CUDA 插件文件已打包，但没有 GPU 不能验证 CUDA Context。

如果失败，保留 build.log 和容器，把最后的报错发回。不要自动清理或反复生成新容器。
下载中断后可按 build.log 诊断；已退出容器可用 `docker start -a 容器名` 重新启动原命令。
若环境只创建了一部分，脚本拒绝自动覆盖，先诊断再修复。

## 上传产物：只有构建成功后执行

将脚本最后列出的两个文件上传到服务器 `~/openmm_rna_setup/`：

- `openmm_rna_offline_bundle.tar`：含完整 Linux Conda 环境和安装/检查脚本，大小以实际构建为准。
- `openmm_rna_offline_bundle.tar.sha256`：校验文件。

在服务器执行：

```bash
cd "$HOME/openmm_rna_setup"
sha256sum -c openmm_rna_offline_bundle.tar.sha256
mkdir -p offline_bundle_20261117
tar -xf openmm_rna_offline_bundle.tar -C offline_bundle_20261117
cd offline_bundle_20261117
bash install_offline_server.sh "$HOME/miniconda3/envs/openmm_rna_ol3"
```

如果 `offline_bundle_20261117` 已用过，换新目录后再解压；环境 prefix 若已存在安装器拒绝覆盖。
服务器安装不调用 conda info/create/solve，不联网，不需要 sudo。
可从当前 protenix shell 启动；安装在子 shell 内激活新环境。保留 `RNA_MD_OFFLINE_INSTALL_CPU_OK` 和报告路径。

## CUDA 验收：CPU 安装成功之后

### 旧安装包第 28 行静默失败的恢复

若旧包在哈希校验后报 `OFFLINE INSTALL FAILED at line 28`，解压和 conda-unpack 已通过，
第 28 行是 CPU 验收子 shell 的结尾，不是解压命令。旧脚本在严格 Bash 模式下 source
conda-pack 的 activate；已有 Protenix 环境时，`type deactivate` 返回非零可导致静默退出。
已用包内真实 activate 脚本复现此兼容问题。新版安装器直接设置 prefix/PATH 并使用新环境 Python。
不要为此重新安装或删除环境。在服务器直接继续 CPU 验收：

```bash
RNA_MD_ENV="$HOME/miniconda3/envs/openmm_rna_ol3"
env -u PYTHONPATH -u PYTHONHOME -u OPENMM_PLUGIN_DIR -u CONDA_OVERRIDE_CUDA \
  PATH="$RNA_MD_ENV/bin:$PATH" CONDA_PREFIX="$RNA_MD_ENV" AMBERHOME="$RNA_MD_ENV" \
  CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  "$RNA_MD_ENV/bin/python" -u \
  "$HOME/openmm_rna_setup/offline_bundle_20261117/check_environment.py" --platform CPU
```

成功标志为 `RNA_MD_CPU_OK`。若仍失败，提供完整 traceback 和输出目录中的 report.json。
本次仅修改本地安装器与本说明，没有修改已生成 bundle 或其 SHA256 清单；旧包恢复不需要上传文件。

使用现有 Conda 的 activate 功能进入新 prefix，不需要 conda info：

```bash
conda activate "$HOME/miniconda3/envs/openmm_rna_ol3"
unset PYTHONPATH PYTHONHOME AMBERHOME OPENMM_PLUGIN_DIR CONDA_OVERRIDE_CUDA
cd "$HOME/openmm_rna_setup/offline_bundle_20261117"
RNA_MD_GPU='填写你获准使用的一张GPU编号或UUID'
CUDA_VISIBLE_DEVICES="$RNA_MD_GPU" python check_environment.py --platform CUDA
```

如果原 Conda 激活也卡住，可在独立子 shell 中使用打包环境自己的 activate：

```bash
(
  unset PYTHONPATH PYTHONHOME AMBERHOME OPENMM_PLUGIN_DIR CONDA_OVERRIDE_CUDA
  source "$HOME/miniconda3/envs/openmm_rna_ol3/bin/activate"
  RNA_MD_GPU='填写你获准使用的一张GPU编号或UUID'
  CUDA_VISIBLE_DEVICES="$RNA_MD_GPU" python \
    "$HOME/openmm_rna_setup/offline_bundle_20261117/check_environment.py" --platform CUDA
)
```

仅使用分配给你的 GPU，不按空闲显存自动选卡。成功标志 `RNA_MD_CUDA_OK`。
把安装日志末尾与 CUDA 的 report.json 发回。20 步合成 RNA 仅验证软件，不代表生产体系平衡/采样。

## 本轮新增和清理

新增 `prepare_offline_macos.sh`、`build_in_container.sh`、`install_offline_server.sh`、本说明。
更新主安装说明；检查脚本沿用之前版本。没有启动实际依赖构建：当前助手会话访问本机 Docker socket 被拒绝，
用户可在 Mac 终端执行上述命令。代码准备包不等于完整依赖离线包。
构建成功后可删除构建容器、中间目录和代码准备包，建议先保存日志/精确版本；实际安装环境需要保留。
服务器 bundle 在完成验收并保存来源记录后可删除；环境内无指向 bundle 的模型权重或源码依赖。

依据：
- https://conda.github.io/conda-pack/
- https://docs.openmm.org/latest/userguide/application/01_getting_started.html
- https://docs.nvidia.com/cuda/archive/12.6.0/cuda-toolkit-release-notes/index.html
- https://github.com/conda-forge/miniforge/releases/expanded_assets/26.9.4-2
