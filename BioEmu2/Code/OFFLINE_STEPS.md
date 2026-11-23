# BioEmu2 离线安装：Mac 构建，Linux 服务器运行

已确认：服务器 Debian 12 / x86_64 / glibc 2.36 / GCC 12.2 / CUDA Toolkit 12.6 / H20 CC 9.0 / 驱动 575.57.08；必要下载地址在服务器超时。Mac Docker 的 linux/amd64 Python 3.12 容器已能访问必要站点。

本方案使用 Python 3.12、官方 cuda12 extra、Miniforge 与 conda-pack。使用独立环境，不修改现有训练环境。脚本是待执行的安装工具，未宣称构建或 GPU 验证已完成。

## 1. 在 Mac 构建

本地终端执行：

```bash
cd /Users/fudanxth/Learning/Laboratory/Admis/graduate_first/RNAMD/BioEmu2/Code
bash prepare_offline_macos.sh
```

脚本创建 `../Offline/时间戳_PID/`，保持 Mac 唤醒、终端开启并留足 Docker Desktop 虚拟磁盘空间。需要下载 Linux Conda、CUDA/PyTorch 依赖和模型权重；ARM 上 x86 模拟和压缩可能耗时较长，不承诺固定时间。宿主机磁盘充足不等于 Docker 虚拟磁盘限额充足。

只在最后出现 `BUILD COMPLETE` 时上传产物：

```text
bioemu2_offline_bundle.tar
bioemu2_offline_bundle.tar.sha256
```

输出目录还含 `build.log`、`container_name.txt`、缓存及展开的 bundle。失败时保留它们，将错误附近日志发回；不自行降低 torch 版本或跳过依赖检查。

容器没有自动删除，失败后修复原因可恢复原容器执行：

```bash
docker start -ai 容器名
```

### Debian HTTP 80 超时的恢复（2026-11-12）

若错误为 `Unable to connect to deb.debian.org:http`，构建脚本已更新为：在容器内将官方 Debian HTTP 源改为 HTTPS，同时兼容 `.sources` 和 `.list`；先验证主仓库和安全仓库 HTTPS，再以有限超时和重试运行 apt。不会关闭 TLS 验证或软件包签名验证，不改 Mac/服务器的软件源。

脚本目录是只读挂载，宿主机更新文件后原容器重启会读取更新后的脚本，不需要重新创建容器。对本次失败目录，在 Mac 执行：

```bash
BIOEMU2_RUN='/Users/fudanxth/Learning/Laboratory/Admis/graduate_first/RNAMD/BioEmu2/Offline/20261112_172413_86250'
BIOEMU2_CONTAINER="$(cat "$BIOEMU2_RUN/container_name.txt")"
set -o pipefail
caffeinate -i docker start -ai "$BIOEMU2_CONTAINER" 2>&1 | tee "$BIOEMU2_RUN/resume_https.log"
```

预期先看到两个 `Debian HTTPS OK`，然后安装系统依赖。继续使用原容器及其已有文件；软件包是否需重新下载取决于 APT 缓存是否仍存在。若 HTTPS 检查也失败，提供 `resume_https.log`，先诊断 Debian HTTPS 访问，不使用 `--fix-missing` 跳过必需依赖。

恢复成功后的产物仍在该 `BIOEMU2_RUN` 目录，仍以 `BUILD COMPLETE` 为完成标志。

### Miniforge 校验附件 404 的恢复（2026-11-12）

旧脚本错误地假定未带版本号的安装器也有同名 `.sha256` 附件；官方 release 为带版本号的安装器提供校验附件。脚本已固定 Miniforge `26.9.4-2` 和官方发布的 Linux x86_64 安装器 SHA256：

```text
bbaf16b3897da24c4be50315934ba74848f617b4495982841d6a0a60e0edbbdf
```

本次已下载的 122 MB 安装器在宿主机计算出的 SHA256 与该值一致。修复脚本会在容器内再次验证并复用它，不再访问错误的未版本化校验文件地址；仅当文件缺失或不匹配时才从固定版本 URL 下载并验证新文件。恢复命令和上节相同，日志文件可改为 `resume_miniforge.log`。预期看到 `Reusing verified Miniforge 26.9.4-2 installer` 和安装器 `OK`，然后安装 Miniforge。

哈希来源：https://github.com/conda-forge/miniforge/releases/expanded_assets/26.9.4-2

### conda-pack 报 pip 文件被覆盖的恢复（2026-11-12）

旧脚本在 Conda 创建环境后运行 `pip install --upgrade pip`，日志确认它将 Conda 的 pip 26.2.2 替换为 PyPI 的 pip 26.3，导致 Conda 包记录与实际文件不一致。新版删除该升级步骤；pip、setuptools 和 wheel 由 Conda 管理。

恢复旧容器时，脚本检查这三个工具的 Conda 记录、已安装版本和元数据文件；仅对受影响的工具卸载 PyPI 分发，再通过 Conda 缓存按原始精确版本及构建号强制重装，并冻结已安装的依赖。不会卸载 torch 或 BioEmu2，也不跳过 conda-pack 检查。若原始缓存已被手工清理而离线恢复失败，应提供日志，不能改用忽略文件缺失参数。

在 Mac 执行：

```bash
set -o pipefail
caffeinate -i docker start -ai bioemu2-offline-20261112_172413_86250 \
  2>&1 | tee '/Users/fudanxth/Learning/Laboratory/Admis/graduate_first/RNAMD/BioEmu2/Offline/20261112_172413_86250/resume_condapack.log'
```

预期看到 `Restoring original Conda tools: [('pip', '26.2.2')]`，之后重新检查并打包。权重文件已下载，继续复用当前目录及其下载缓存；不重新创建构建容器。新的 `pip_list.json` 记录含 pip 在内的全部已安装包，修复采用的原始包 URL 写入 `conda_tools_repair.txt`。

### Conda 空事务后仍 No module named pip 的恢复（2026-11-12）

上次使用 `@EXPLICIT` URL 文件执行重装有误：Conda 26.9 的显式安装分支会在版本记录匹配时跳过链接，即使实际文件已被 pip 删除；因此执行事务显示成功但没有恢复 pip。已改为常规版本规格 `pip=26.2.2=pyh8b19718_2` 搭配 `--force-reinstall --freeze-installed --offline`，使用原包缓存恢复文件。仅恢复工具包，其他依赖保持冻结；不删除或重建环境。

此外，继续运行前会检查恢复后的 distribution 元数据及 `python -m pip --version`；不能只根据 Conda 返回码判断修复成功。Mac 恢复命令：

```bash
set -o pipefail
caffeinate -i docker start -ai bioemu2-offline-20261112_172413_86250 \
  2>&1 | tee '/Users/fudanxth/Learning/Laboratory/Admis/graduate_first/RNAMD/BioEmu2/Offline/20261112_172413_86250/resume_pip_restore.log'
```

预期在第 2 步出现 `Conda tool restoration verified.` 和 `pip 26.2.2 from /opt/bioemu2/...`，然后进入第 3/4 步。Conda 安装步骤应有 pip 的实际卸载/重装计划。若再失败，保留日志，不运行 ensurepip 或手动改写 conda-meta 作为绕过。

Conda 26.9 实现依据：https://github.com/conda/conda/blob/26.9.4/conda/misc.py#L128

容器名见输出目录 `container_name.txt`。从 Mac 休眠/终端关闭恢复时，先用 `docker ps -a` 核对容器是否还在运行，避免同时启动两个构建。运行中的日志可用 `docker logs -f 容器名` 查看。恢复运行的日志仍保存在 Docker 中，不会自动追加旧的 build.log。

构建使用源仓库当前提交，自动记录 commit；同一容器恢复时不 git pull。模型 checkpoint/config 取自同一个记录的 Hugging Face revision。完整包含来源、环境版本、SHA256、源码快照和标准 RNA 的 CPU 离线检查结果。安装后仍需目标 GPU 验证。

## 2. 用户上传

使用你实际登录 tinghao.xia 账户的 SSH 目标/端口/跳板设置。此前本机两个 root SSH 配置不一定直接对应这个用户会话，不能据此猜测上传目标。

在 Mac 终端将以下两个变量替换为真实值：

```bash
BIOEMU2_SERVER='你实际使用的SSH目标或别名'
BIOEMU2_RUN='/Users/fudanxth/Learning/Laboratory/Admis/graduate_first/RNAMD/BioEmu2/Offline/实际时间戳_PID'
ssh "$BIOEMU2_SERVER" 'mkdir -p "$HOME/bioemu2_setup/offline"'
scp "$BIOEMU2_RUN/bioemu2_offline_bundle.tar" \
    "$BIOEMU2_RUN/bioemu2_offline_bundle.tar.sha256" \
    "$BIOEMU2_SERVER:bioemu2_setup/offline/"
```

如果平时的 SSH 命令手动指定端口，ssh 使用 `-p 端口`，scp 使用 `-P 端口`；推荐在 SSH config 中定义正确账户的别名后使用。

## 3. 在服务器安装

服务器终端执行（`bundle` 和新环境都不能已存在）：

```bash
cd "$HOME/bioemu2_setup/offline"
sha256sum -c bioemu2_offline_bundle.tar.sha256
test ! -e bundle && tar -xf bioemu2_offline_bundle.tar
```

上一步必须校验通过，解压成功后再运行：

```bash
set -o pipefail
bash bundle/install_offline_server.sh 2>&1 | tee install.log
```

默认安装到 `$HOME/miniconda3/envs/bioemu2`。脚本遇到已存在目录直接停止，不覆盖、不自动删除。失败时不要重复覆盖解压，先提供 install.log；需重新尝试时可以指定一个新的空目标：

```bash
bash bundle/install_offline_server.sh "$HOME/miniconda3/envs/bioemu2_retry1"
```

安装过程中不下载软件、不加载权重或使用 GPU。检查成功的标志是 `CPU_OFFLINE_CHECK_OK` 和最终 `OFFLINE_INSTALL_CPU_OK`。Conda base 的版本查询此前超时，若激活步骤也异常需单独诊断，不能用 GPU 驱动调整解决。

完成后激活：

```bash
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate bioemu2
python --version
```

模型位于 `~/bioemu2_setup/offline/bundle/model/checkpoint.ckpt`，同目录保留 `config.yaml`。后续推理显式指定本地 checkpoint，体系使用本地 YAML/CIF。这两个模型文件不在 Conda 环境里，不能误删 bundle/model。

把 install.log 发回，再选择实验室分配的 GPU 验证真实 CUDA 算子、模型加载及短 RNA 传播。本轮 CPU 检查不能证明长链生成质量、显存需求或 GPU 兼容性。

## 文件和清理

- 新增 prepare_offline_macos.sh、build_in_container.sh：本地构建工具，验收完成后可删除。
- 新增 install_offline_server.sh、check_installation.py：会随包上传，验收完成后可删除，建议保留复现。
- 本说明 OFFLINE_STEPS.md：可删除，建议保留。
- Offline 下的日志、源码来源和版本记录建议保留；缓存、展开的环境包和外层传输 tar 会重复占空间，完整验收且另有备份后可清理。
- 保留服务器已安装的环境和 bundle/model 两个权重文件。不要移动已运行 conda-unpack 的环境目录。
- Docker 容器及其 /opt 下的构建环境会占 Docker 虚拟磁盘；目标服务器完整验收后再按记录的容器名删除。本脚本不自动删除容器、清理其他镜像或执行 docker system prune。

官方依据：

- https://github.com/microsoft/bioemu2/blob/main/pyproject.toml
- https://github.com/microsoft/bioemu2/blob/main/docs/checkpoints.md
- https://github.com/conda-forge/miniforge
- https://conda.github.io/conda-pack/
