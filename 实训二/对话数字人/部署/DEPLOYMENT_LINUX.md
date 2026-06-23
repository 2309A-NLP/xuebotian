# Linly-Talker Linux 部署文档

> **文档版本**: v1.0  
> **更新日期**: 2026-06-23  
> **项目**: Linly-Talker 数字人智能对话系统  
> **适用系统**: Ubuntu 20.04+, CentOS 7+, Debian 11+

---

## 目录

- [1. 系统要求](#1-系统要求)
- [2. 基础环境安装](#2-基础环境安装)
- [3. Python 环境配置](#3-python-环境配置)
- [4. 项目部署](#4-项目部署)
- [5. 模型下载](#5-模型下载)
- [6. WebUI 启动](#6-webui-启动)
- [7. 服务化部署](#7-服务化部署)
- [8. Docker 部署](#8-docker-部署)
- [9. 常见问题](#9-常见问题)

---

## 1. 系统要求

### 1.1 硬件要求

| 组件 | 最低要求 | 推荐配置 |
|------|----------|----------|
| **GPU** | 6GB 显存 | 12GB+ 显存 (RTX 3060, RTX 3090, A5000 等) |
| **内存** | 8GB RAM | 16GB+ RAM |
| **存储** | 50GB 可用空间 | 100GB+ SSD |
| **CPU** | 4 核 | 8 核+ |

### 1.2 软件要求

| 组件 | 版本要求 | 说明 |
|------|----------|------|
| **操作系统** | Ubuntu 20.04+ / CentOS 7+ / Debian 11+ | 推荐 Ubuntu 22.04 |
| **CUDA** | 11.8 / 12.1 / 12.4 | 推荐 CUDA 12.1 |
| **cuDNN** | 8.x | 与 CUDA 版本匹配 |
| **Python** | 3.10 | 必须使用 Python 3.10 |
| **GCC** | 9.x+ | 编译某些 C++ 扩展 |

### 1.3 检查 GPU 可用性

```bash
# 检查 NVIDIA 驱动
nvidia-smi

# 检查 CUDA 版本
nvcc --version

# 示例输出:
# +-----------------------------------------------------------------------------+
# | NVIDIA-SMI 525.85.05   Driver Version: 525.85.05   CUDA Version: 12.0     |
# |-------------------------------+----------------------+----------------------+
# | GPU  Name        Persistence-M| Bus-Id        Disp.A | Volatile Uncorr. ECC |
# | Fan  Temp  Perf  Pwr:Usage/Cap|         Memory-Usage | GPU-Util  Compute M. |
# |===============================+======================+======================|
# |   0  NVIDIA GeForce ...  Off  | 00000000:01:00.0 On |                  0 MiB |
# |  0%   44C    P0    29W / 350W |      0MiB /  24576MiB |      0%      Default |
# +-------------------------------+----------------------+----------------------+
```

---

## 2. 基础环境安装

### 2.1 系统更新

**Ubuntu / Debian:**

```bash
# 更新系统包
sudo apt update && sudo apt upgrade -y

# 安装基础工具
sudo apt install -y build-essential git curl wget unzip \
    software-properties-common ca-certificates \
    libssl-dev libffi-dev python3-dev
```

**CentOS / RHEL:**

```bash
# 更新系统包
sudo yum update -y

# 安装基础工具
sudo yum groupinstall -y "Development Tools"
sudo yum install -y git curl wget unzip \
    openssl-devel libffi-devel python3-devel
```

### 2.2 安装 FFmpeg

**Ubuntu / Debian:**

```bash
# 添加 FFmpeg 仓库
sudo add-apt-repository ppa:jonathonf/ffmpeg-4

# 安装 FFmpeg
sudo apt update
sudo apt install -y ffmpeg

# 验证安装
ffmpeg -version
```

**CentOS:**

```bash
# 从 EPEL 安装
sudo yum install -y epel-release
sudo yum install -y ffmpeg

# 或从源码编译安装（推荐）
wget https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
tar -xf ffmpeg-release-amd64-static.tar.xz
sudo mv ffmpeg /usr/local/bin/
```

### 2.3 安装音频依赖

```bash
# Ubuntu / Debian
sudo apt install -y libasound2-dev portaudio19-dev libportaudio2 libportaudiocpp0 libsox-dev

# CentOS
sudo yum install -y alsa-lib-devel portaudio-devel sox sox-devel
```

### 2.4 安装 CUDA 和 cuDNN

#### 方式一：从 NVIDIA 官方安装

```bash
# 下载 CUDA Toolkit
wget https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-wsl-ubuntu.pin
sudo mv cuda-wsl-ubuntu.pin /etc/apt/preferences.d/cuda-repository-pin-600
wget https://developer.download.nvidia.com/compute/cuda/12.1.1/local_installers/cuda_12.1.1_530.30.02_linux.run
sudo sh cuda_12.1.1_530.30.02_linux.run
```

#### 方式二：使用 conda 安装（推荐）

```bash
# 安装 Miniconda
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh

# 按照提示完成安装
# 重启终端或运行
source ~/.bashrc
```

---

## 3. Python 环境配置

### 3.1 创建虚拟环境

```bash
# 使用 conda 创建 Python 3.10 环境
conda create -n linly python=3.10 -y
conda activate linly

# 验证 Python 版本
python --version
# 输出: Python 3.10.x
```

### 3.2 安装 PyTorch

```bash
# 根据 CUDA 版本选择安装命令

# CUDA 11.8
pip install torch==2.4.1 torchvision==0.19.1 torchaudio==2.4.1 \
    --index-url https://download.pytorch.org/whl/cu118

# CUDA 12.1
pip install torch==2.4.1 torchvision==0.19.1 torchaudio==2.4.1 \
    --index-url https://download.pytorch.org/whl/cu121

# CUDA 12.4
pip install torch==2.4.1 torchvision==0.19.1 torchaudio==2.4.1 \
    --index-url https://download.pytorch.org/whl/cu124
```

### 3.3 配置 pip 源

```bash
# 使用清华镜像源加速下载
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 或使用阿里云镜像
pip config set global.index-url https://mirrors.aliyun.com/pypi/simple
```

### 3.4 安装项目依赖

```bash
# 升级 pip
python -m pip install --upgrade pip

# 安装 Gradio（使用夜间版本以获得最新功能）
pip install tb-nightly -i https://mirrors.aliyun.com/pypi/simple

# 安装项目依赖
pip install -r requirements_webui.txt
```

### 3.5 安装 MuseTalk 相关依赖

```bash
# 安装 OpenMIM 和 MMSeries
pip install --no-cache-dir -U openmim
mim install mmengine
mim install "mmcv>=2.0.1"
mim install "mmdet>=3.1.0"
mim install "mmpose>=1.1.0"
```

### 3.6 安装 NeRF 相关依赖（可选）

```bash
# 安装 PyTorch3D
pip install "git+https://github.com/facebookresearch/pytorch3d.git"

# 如果安装失败，运行脚本
python scripts/install_pytorch3d.py

# 安装其他 NeRF 依赖
pip install -r TFG/requirements_nerf.txt
```

### 3.7 验证安装

```bash
# 验证 PyTorch 和 CUDA
python -c "import torch; print(f'PyTorch: {torch.__version__}'); print(f'CUDA Available: {torch.cuda.is_available()}'); print(f'CUDA Version: {torch.version.cuda}')"

# 验证 FFmpeg
ffmpeg -version | head -n 1

# 验证其他依赖
python -c "import gradio; import transformers; print('Dependencies OK')"
```

---

## 4. 项目部署

### 4.1 克隆项目代码

```bash
# 进入工作目录
cd ~  # 或 cd /path/to/your/workspace

# 克隆项目
git clone https://github.com/Kedreamix/Linly-Talker.git --depth 1

# 进入项目目录
cd Linly-Talker

# 初始化子模块（如有）
git submodule update --init --recursive
```

### 4.2 创建必要目录

```bash
# 创建输入输出目录
mkdir -p inputs
mkdir -p outputs
mkdir -p temp
mkdir -p checkpoints
mkdir -p logs

# 创建 HTTPS 证书目录（麦克风对话需要）
mkdir -p https_cert
```

### 4.3 配置权限

```bash
# 设置执行权限
chmod +x scripts/*.sh

# 设置目录权限
chmod 755 inputs outputs temp
```

### 4.4 环境变量配置

```bash
# 创建环境变量配置文件
cat > ~/.bashrc.linly << 'EOF'
# Linly-Talker Environment Variables
export LINLY_HOME=/path/to/Linly-Talker
export GRADIO_TEMP_DIR=$LINLY_HOME/temp
export WEBUI=true

# CUDA 配置
export CUDA_HOME=/usr/local/cuda
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
export PATH=$CUDA_HOME/bin:$PATH
EOF

# 加载环境变量
source ~/.bashrc.linly

# 永久生效（添加到 .bashrc）
echo "source ~/.bashrc.linly" >> ~/.bashrc
```

---

## 5. 模型下载

### 5.1 使用下载脚本（推荐）

项目提供了自动下载脚本：

```bash
# 运行下载脚本
bash scripts/download_models.sh

# 脚本会提示选择下载源：
# 1. ModelScope（推荐国内用户）
# 2. HuggingFace
# 3. HuggingFace 镜像
```

### 5.2 手动下载

#### 5.2.1 主要模型下载

```bash
# 使用 HuggingFace CLI
pip install -U huggingface_hub

# 设置镜像（可选）
export HF_ENDPOINT=https://hf-mirror.com

# 下载主模型
huggingface-cli download --resume-download \
    --local-dir-use-symlinks False \
    Kedreamix/Linly-Talker \
    --local-dir ./Linly-Talker-models
```

#### 5.2.2 Qwen 模型下载

```bash
# 创建目录
mkdir -p Qwen

# 下载 Qwen-1.8B
git lfs install
git clone https://huggingface.co/Qwen/Qwen-1_8B-Chat Qwen/Qwen-1_8B-Chat
```

#### 5.2.3 SadTalker 模型下载

```bash
# 运行 SadTalker 下载脚本
bash scripts/sadtalker_download_models.sh
```

### 5.3 模型目录结构

```bash
Linly-Talker/
├── checkpoints/                 # 数字人模型
│   ├── SadTalker_V0.0.2_256.safetensors
│   ├── wav2lip_gan.pth
│   ├── mapping_00109-model.pth.tar
│   ├── mapping_00229-model.pth.tar
│   └── ...
├── Whisper/                     # Whisper 模型
│   ├── base.pt
│   └── tiny.pt
├── FunASR/                      # FunASR 模型
│   └── ...
├── GPT_SoVITS/pretrained_models/  # 语音克隆
│   └── ...
├── MuseTalk/models/             # MuseTalk 模型
│   └── ...
└── Qwen/                        # Qwen LLM
    └── Qwen-1_8B-Chat/
```

### 5.4 验证模型

```bash
# 检查模型文件
ls -lh checkpoints/
ls -lh Qwen/
ls -lh Whisper/

# 检查关键文件大小
# SadTalker 权重约 174MB
# Wav2Lip 权重约 200MB
# Qwen-1.8B 约 4GB
```

---

## 6. WebUI 启动

### 6.1 修改配置文件

编辑 `configs.py`：

```python
# configs.py
port = 6006                     # WebUI 端口
ip = '0.0.0.0'                 # 0.0.0.0 允许外部访问
api_port = 7871

mode = 'offline'
model_path = 'Qwen/Qwen-1_8B-Chat'

# SSL 配置（麦克风对话需要）
ssl_certfile = "./https_cert/cert.pem"
ssl_keyfile = "./https_cert/key.pem"
```

### 6.2 生成 SSL 证书（可选）

```bash
# 使用 OpenSSL 生成自签名证书
cd https_cert

openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem \
    -days 365 -nodes \
    -subj "/CN=localhost"

cd ..
```

### 6.3 启动 WebUI

#### 方式一：直接启动

```bash
# 激活环境
conda activate linly

# 启动 WebUI
python webui.py
```

#### 方式二：指定参数启动

```bash
python webui.py \
    --listen 0.0.0.0 \
    --port 6006 \
    --share
```

#### 方式三：后台运行

```bash
# 使用 nohup 后台运行
nohup python webui.py > logs/webui.log 2>&1 &

# 或使用 screen
screen -S linly
python webui.py
# Ctrl+A, D 返回主终端
```

### 6.4 访问 WebUI

启动成功后，访问以下地址：

```
本地访问: http://localhost:6006
局域网访问: http://<服务器IP>:6006
公网访问: http://<公网IP>:6006 （需配置防火墙）
```

### 6.5 启动脚本

创建启动脚本 `start.sh`：

```bash
#!/bin/bash
# Linly-Talker 启动脚本

# 激活 conda 环境
eval "$(conda shell.bash hook)"
conda activate linly

# 设置环境变量
export GRADIO_TEMP_DIR=./temp
export WEBUI=true

# 清理 GPU 缓存
python -c "import torch; torch.cuda.empty_cache()"

# 启动 WebUI
python webui.py \
    --listen 0.0.0.0 \
    --port 6006

# 保持终端打开（调试用）
read -p "按 Enter 键退出..."
```

赋予执行权限：

```bash
chmod +x start.sh
```

---

## 7. 服务化部署

### 7.1 Systemd 服务

创建 systemd 服务文件：

```bash
sudo nano /etc/systemd/system/linly-talker.service
```

写入以下内容：

```ini
[Unit]
Description=Linly-Talker Digital Human Service
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/Linly-Talker
ExecStart=/home/your_username/miniconda3/envs/linly/bin/python webui.py
Restart=on-failure
RestartSec=10
StandardOutput=append:/path/to/Linly-Talker/logs/webui.log
StandardError=append:/path/to/Linly-Talker/logs/webui.error.log

# 环境变量
Environment="GRADIO_TEMP_DIR=/path/to/Linly-Talker/temp"
Environment="WEBUI=true"

[Install]
WantedBy=multi-user.target
```

启用服务：

```bash
# 重载 systemd
sudo systemctl daemon-reload

# 启用服务
sudo systemctl enable linly-talker

# 启动服务
sudo systemctl start linly-talker

# 查看状态
sudo systemctl status linly-talker

# 查看日志
sudo journalctl -u linly-talker -f
```

### 7.2 Supervisor 管理

安装 supervisor：

```bash
sudo apt install -y supervisor
```

创建配置：

```bash
sudo nano /etc/supervisor/conf.d/linly-talker.conf
```

写入：

```ini
[program:linly-talker]
command=/home/username/miniconda3/envs/linly/bin/python webui.py
directory=/path/to/Linly-Talker
user=username
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/path/to/Linly-Talker/logs/webui.log
environment=GRADIO_TEMP_DIR="/path/to/Linly-Talker/temp",WEBUI="true"
```

管理服务：

```bash
# 重载配置
sudo supervisorctl reread
sudo supervisorctl update

# 管理命令
sudo supervisorctl start linly-talker
sudo supervisorctl stop linly-talker
sudo supervisorctl restart linly-talker
sudo supervisorctl status linly-talker
```

### 7.3 Nginx 反向代理

安装 Nginx：

```bash
sudo apt install -y nginx
```

创建站点配置：

```bash
sudo nano /etc/nginx/sites-available/linly-talker
```

写入：

```nginx
upstream linly_backend {
    server 127.0.0.1:6006;
}

server {
    listen 80;
    server_name your-domain.com;  # 或服务器 IP

    # 反向代理到 Gradio
    location / {
        proxy_pass http://linly_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket 支持
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # 超时设置
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
```

启用配置：

```bash
# 测试配置
sudo nginx -t

# 启用站点
sudo ln -s /etc/nginx/sites-available/linly-talker /etc/nginx/sites-enabled/

# 重载 Nginx
sudo systemctl reload nginx
```

### 7.4 HTTPS 配置

使用 Let's Encrypt 免费证书：

```bash
# 安装 Certbot
sudo apt install -y certbot python3-certbot-nginx

# 获取证书
sudo certbot --nginx -d your-domain.com

# 自动续期测试
sudo certbot renew --dry-run
```

---

## 8. Docker 部署

### 8.1 安装 Docker

```bash
# 安装 Docker
curl -fsSL https://get.docker.com | bash

# 启动 Docker
sudo systemctl start docker
sudo systemctl enable docker

# 添加当前用户到 docker 组
sudo usermod -aG docker $USER
newgrp docker
```

### 8.2 创建 Dockerfile

```dockerfile
# Dockerfile
FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

# 设置环境变量
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    ffmpeg \
    libasound2-dev \
    portaudio19-dev \
    libsox-dev \
    git \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制项目文件
COPY . .

# 安装 Python 依赖
RUN pip install --no-cache-dir torch==2.4.1 torchvision==0.19.1 torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cu121
RUN pip install --no-cache-dir -r requirements_webui.txt

# 安装 MuseTalk 依赖
RUN pip install --no-cache-dir -U openmim && \
    mim install mmengine "mmcv>=2.0.1" "mmdet>=3.1.0" "mmpose>=1.1.0"

# 创建必要目录
RUN mkdir -p inputs outputs temp checkpoints logs

# 暴露端口
EXPOSE 6006

# 启动命令
CMD ["python", "webui.py"]
```

### 8.3 构建镜像

```bash
# 构建镜像
docker build -t linly-talker:latest .

# 或使用预构建镜像
docker pull registry.cn-beijing.aliyuncs.com/codewithgpu2/kedreamix-linly-talker:afGA8RPDLf
```

### 8.4 运行容器

#### 基础运行

```bash
# 运行容器
docker run --gpus all \
    --name linly-talker \
    -p 6006:6006 \
    -v $(pwd)/checkpoints:/app/checkpoints \
    -v $(pwd)/inputs:/app/inputs \
    -v $(pwd)/outputs:/app/outputs \
    -v $(pwd)/temp:/app/temp \
    -e GRADIO_TEMP_DIR=/app/temp \
    -d \
    linly-talker:latest
```

#### 带 GPU 支持

```bash
# NVIDIA Docker 运行时
docker run --gpus all \
    --name linly-talker \
    -p 6006:6006 \
    --shm-size=16g \
    -v $(pwd):/app \
    -w /app \
    -e NVIDIA_VISIBLE_DEVICES=all \
    -d \
    linly-talker:latest
```

### 8.5 Docker Compose 部署

创建 `docker-compose.yml`：

```yaml
version: '3.8'

services:
  linly-talker:
    build: .
    image: linly-talker:latest
    container_name: linly-talker
    ports:
      - "6006:6006"
    volumes:
      - ./checkpoints:/app/checkpoints
      - ./inputs:/app/inputs
      - ./outputs:/app/outputs
      - ./temp:/app/temp
      - ./logs:/app/logs
      - ./Qwen:/app/Qwen
    environment:
      - GRADIO_TEMP_DIR=/app/temp
      - WEBUI=true
      - CUDA_VISIBLE_DEVICES=0
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6006"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
```

启动服务：

```bash
# 启动
docker-compose up -d

# 查看状态
docker-compose ps

# 查看日志
docker-compose logs -f

# 停止
docker-compose down
```

---

## 9. 常见问题

### 9.1 安装问题

#### GLIBCXX 版本问题

```bash
# 查看当前版本
strings /usr/lib/x86_64-linux-gnu/libstdc++.so.6 | grep GLIBCXX

# 升级 libstdc++
sudo add-apt-repository ppa:ubuntu-toolchain-r/test
sudo apt update
sudo apt install -y gcc-11 g++-11
```

#### PyTorch 版本不兼容

```bash
# 卸载旧版本
pip uninstall torch torchvision torchaudio

# 重新安装正确版本
pip install torch==2.4.1 torchvision==0.19.1 torchaudio==2.4.1 \
    --index-url https://download.pytorch.org/whl/cu121
```

### 9.2 模型加载问题

#### 模型文件损坏

```bash
# 重新下载损坏的文件
wget -c https://modelscope.cn/api/v1/models/Kedreamix/Linly-Talker/repo?Revision=master&FilePath=checkpoints%2Fmapping_00109-model.pth.tar
```

#### 模型路径错误

```bash
# 检查 checkpoints 目录结构
ls -la checkpoints/

# 修复路径
mv checkpoints/sadtalker/* checkpoints/
rmdir checkpoints/sadtalker
```

### 9.3 运行时问题

#### 显存不足

```bash
# 清理显存
python -c "import torch; torch.cuda.empty_cache()"

# 或在启动前设置
export PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb=512
```

#### 端口被占用

```bash
# 查看端口占用
lsof -i :6006

# 杀死进程
kill -9 <PID>

# 或使用其他端口
sed -i 's/port = 6006/port = 6007/' configs.py
```

### 9.4 性能问题

#### GPU 利用率低

```bash
# 设置 cuDNN 优化
python -c "import torch; torch.backends.cudnn.benchmark = True"
```

#### 推理速度慢

```bash
# 使用较小的模型
# 替换 Qwen-7B 为 Qwen-1.8B
sed -i "s/Qwen-7B/Qwen-1_8B-Chat/" configs.py

# 减少 batch_size
sed -i 's/batch_size=4/batch_size=2/' webui.py
```

### 9.5 网络问题

#### 模型下载慢

```bash
# 使用镜像站
export HF_ENDPOINT=https://hf-mirror.com

# 使用 modelscope
pip install modelscope
python -c "from modelscope import snapshot_download; snapshot_download('Kedreamix/Linly-Talker')"
```

#### SSL 证书问题

```bash
# 跳过 SSL 验证（仅用于测试）
export GIT_SSL_NO_VERIFY=1
git config --global http.sslVerify false
```

---

## 附录

### A. 快速部署脚本

创建一键部署脚本 `deploy.sh`：

```bash
#!/bin/bash
set -e

echo "=== Linly-Talker 快速部署脚本 ==="

# 1. 安装系统依赖
echo "[1/7] 安装系统依赖..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y build-essential git curl wget unzip ffmpeg \
    libasound2-dev portaudio19-dev libsox-dev

# 2. 安装 Miniconda
echo "[2/7] 安装 Miniconda..."
if [ ! -d "$HOME/miniconda3" ]; then
    wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh
    bash /tmp/miniconda.sh -b -p $HOME/miniconda3
    rm /tmp/miniconda.sh
fi
eval "$($HOME/miniconda3/bin/conda shell.bash hook)"

# 3. 创建环境
echo "[3/7] 创建 Python 环境..."
conda create -n linly python=3.10 -y
conda activate linly

# 4. 安装 PyTorch
echo "[4/7] 安装 PyTorch..."
pip install torch==2.4.1 torchvision==0.19.1 torchaudio==2.4.1 \
    --index-url https://download.pytorch.org/whl/cu121

# 5. 配置 pip 源
echo "[5/7] 配置 pip 源..."
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 6. 安装项目依赖
echo "[6/7] 安装项目依赖..."
pip install -r requirements_webui.txt
pip install --no-cache-dir -U openmim
mim install mmengine "mmcv>=2.0.1" "mmdet>=3.1.0" "mmpose>=1.1.0"

# 7. 下载模型
echo "[7/7] 下载模型..."
bash scripts/download_models.sh

echo "=== 部署完成 ==="
echo "运行以下命令启动："
echo "  conda activate linly"
echo "  python webui.py"
```

赋予执行权限并运行：

```bash
chmod +x deploy.sh
./deploy.sh
```

### B. 防火墙配置

```bash
# Ubuntu ufw
sudo ufw allow 6006/tcp
sudo ufw enable

# CentOS firewalld
sudo firewall-cmd --permanent --add-port=6006/tcp
sudo firewall-cmd --reload
```

### C. 监控脚本

创建监控脚本 `monitor.sh`：

```bash
#!/bin/bash
while true; do
    clear
    echo "=== Linly-Talker 监控 ==="
    echo "时间: $(date)"
    echo ""
    echo "--- GPU 状态 ---"
    nvidia-smi --query-gpu=index,name,temperature.gpu,utilization.gpu,utilization.memory,memory.used,memory.total --format=csv
    echo ""
    echo "--- 进程状态 ---"
    ps aux | grep "[w]ebui.py"
    echo ""
    echo "--- 显存使用 ---"
    python -c "import torch; print(f'已分配: {torch.cuda.memory_allocated()/1024**3:.2f} GB'); print(f'已缓存: {torch.cuda.memory_reserved()/1024**3:.2f} GB')"
    sleep 5
done
```

### D. 联系方式

- **GitHub**: https://github.com/Kedreamix/Linly-Talker
- **问题反馈**: https://github.com/Kedreamix/Linly-Talker/issues
- **B站视频**: https://www.bilibili.com/video/BV1rN4y1a76x/

---

*本文档由 AI 生成，如有问题请联系项目维护者*
