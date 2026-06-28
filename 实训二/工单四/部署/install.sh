#!/bin/bash

#===============================================================================
# 基金问答智能体 - Linux 部署脚本
# 适用系统: Ubuntu 20.04+ / CentOS 8+ / Debian 11+
# 作者: FinQwen Team
# 版本: 1.0.0
#===============================================================================

set -e  # 遇到错误立即退出
set -u  # 使用未定义的变量时报错

#-------------------------------------------------------------------------------
# 配置变量
#-------------------------------------------------------------------------------

# 应用配置
APP_NAME="fund-qa-agent"
APP_USER="appuser"
APP_DIR="/opt/${APP_NAME}"
DATA_DIR="/var/lib/${APP_NAME}"
LOG_DIR="/var/log/${APP_NAME}"
CONFIG_DIR="/etc/${APP_NAME}"

# Python 配置
PYTHON_VERSION="3.10"
VENV_DIR="${APP_DIR}/venv"

# 服务配置
SERVICE_PORT=5000
SERVICE_WORKERS=4
SERVICE_TIMEOUT=300

# 数据库配置
DB_PATH="${DATA_DIR}/data/博金杯比赛数据.db"

# 依赖版本
REQUIRED_PACKAGES=(
    "python${PYTHON_VERSION}"
    "python3-pip"
    "python3-venv"
    "git"
    "curl"
    "nginx"
    "supervisor"
)

#-------------------------------------------------------------------------------
# 颜色定义
#-------------------------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

#-------------------------------------------------------------------------------
# 前置检查
#-------------------------------------------------------------------------------

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "此脚本需要 root 权限运行"
        echo "请使用: sudo $0"
        exit 1
    fi
}

check_os() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        OS=$ID
        VER=$VERSION_ID
        log_info "检测到操作系统: ${PRETTY_NAME}"
    else
        log_error "无法检测操作系统"
        exit 1
    fi

    case $OS in
        ubuntu|debian)
            PKG_MANAGER="apt-get"
            ;;
        centos|rhel|fedora)
            PKG_MANAGER="yum"
            ;;
        *)
            log_error "不支持的操作系统: $OS"
            exit 1
            ;;
    esac
}

#-------------------------------------------------------------------------------
# 系统依赖安装
#-------------------------------------------------------------------------------

install_system_dependencies() {
    log_info "安装系统依赖..."

    case $PKG_MANAGER in
        apt-get)
            apt-get update
            apt-get install -y ${REQUIRED_PACKAGES[@]}
            ;;
        yum)
            yum install -y ${REQUIRED_PACKAGES[@]}
            ;;
    esac

    log_success "系统依赖安装完成"
}

#-------------------------------------------------------------------------------
# Python 环境配置
#-------------------------------------------------------------------------------

install_python() {
    log_info "检查 Python 环境..."

    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &> /dev/null; then
        PYTHON_CMD="python"
    else
        log_error "未找到 Python，请先安装"
        exit 1
    fi

    PYTHON_VERSION_INSTALLED=$(${PYTHON_CMD} --version 2>&1 | awk '{print $2}')
    log_info "当前 Python 版本: ${PYTHON_VERSION_INSTALLED}"

    # 检查 pip
    if ! ${PYTHON_CMD} -m pip --version &> /dev/null; then
        log_info "安装 pip..."
        curl -sS https://bootstrap.pypa.io/get-pip.py | ${PYTHON_CMD}
    fi
}

create_virtualenv() {
    log_info "创建虚拟环境..."

    if [[ -d "${VENV_DIR}" ]]; then
        log_warn "虚拟环境已存在，将重新创建"
        rm -rf ${VENV_DIR}
    fi

    ${PYTHON_CMD} -m venv ${VENV_DIR}
    source ${VENV_DIR}/bin/activate

    log_info "升级 pip..."
    pip install --upgrade pip setuptools wheel

    log_success "虚拟环境创建完成"
}

install_python_dependencies() {
    log_info "安装 Python 依赖..."

    source ${VENV_DIR}/bin/activate

    pip install -r ${APP_DIR}/requirements.txt

    log_success "Python 依赖安装完成"
}

#-------------------------------------------------------------------------------
# 目录创建
#-------------------------------------------------------------------------------

create_directories() {
    log_info "创建目录结构..."

    mkdir -p ${APP_DIR}
    mkdir -p ${DATA_DIR}/data
    mkdir -p ${LOG_DIR}
    mkdir -p ${CONFIG_DIR}

    # 设置权限
    if ! id "${APP_USER}" &> /dev/null; then
        useradd -r -s /bin/false ${APP_USER}
        log_info "创建系统用户: ${APP_USER}"
    fi

    chown -R ${APP_USER}:${APP_USER} ${APP_DIR}
    chown -R ${APP_USER}:${APP_USER} ${DATA_DIR}
    chown -R ${APP_USER}:${APP_USER} ${LOG_DIR}

    log_success "目录创建完成"
}

#-------------------------------------------------------------------------------
# 应用配置
#-------------------------------------------------------------------------------

create_env_file() {
    log_info "创建环境配置文件..."

    ENV_FILE="${CONFIG_DIR}/.env"

    cat > ${ENV_FILE} << 'EOF'
# 基金问答智能体配置文件
# 由 install.sh 自动生成

# SiliconFlow API 配置
SILICONFLOW_API_KEY=your_api_key_here
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1

# 模型配置
MODEL_NAME=deepseek-ai/DeepSeek-V4-Flash
TEMPERATURE=0.1
MAX_TOKENS=4096

# 数据库配置
DB_PATH=/var/lib/fund-qa-agent/data/博金杯比赛数据.db

# Agent 配置
MAX_RETRIES=3
ENABLE_HUMAN_REVIEW=false
EOF

    chmod 600 ${ENV_FILE}
    chown ${APP_USER}:${APP_USER} ${ENV_FILE}

    log_success "配置文件创建完成: ${ENV_FILE}"
}

#-------------------------------------------------------------------------------
# Supervisor 配置
#-------------------------------------------------------------------------------

create_supervisor_config() {
    log_info "创建 Supervisor 配置..."

    SUPERVISOR_CONF="/etc/supervisor/conf.d/${APP_NAME}.conf"

    cat > ${SUPERVISOR_CONF} << EOF
[program:${APP_NAME}]
command=${VENV_DIR}/bin/gunicorn api:app \
    --bind 127.0.0.1:${SERVICE_PORT} \
    --workers ${SERVICE_WORKERS} \
    --timeout ${SERVICE_TIMEOUT} \
    --access-logfile ${LOG_DIR}/access.log \
    --error-logfile ${LOG_DIR}/error.log \
    --log-level info
directory=${APP_DIR}
user=${APP_USER}
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
stderr_logfile=${LOG_DIR}/${APP_NAME}-err.log
stdout_logfile=${LOG_DIR}/${APP_NAME}-out.log
environment=PATH="${VENV_DIR}/bin"
EOF

    log_success "Supervisor 配置创建完成"
}

#-------------------------------------------------------------------------------
# Nginx 配置
#-------------------------------------------------------------------------------

create_nginx_config() {
    log_info "创建 Nginx 配置..."

    NGINX_CONF="/etc/nginx/sites-available/${APP_NAME}.conf"
    NGINX_ENABLED="/etc/nginx/sites-enabled/${APP_NAME}.conf"

    cat > ${NGINX_CONF} << EOF
upstream ${APP_NAME}_backend {
    server 127.0.0.1:${SERVICE_PORT};
}

server {
    listen 80;
    server_name _;

    client_max_body_size 10M;
    client_body_timeout 300s;
    proxy_read_timeout 300s;

    access_log ${LOG_DIR}/nginx-access.log;
    error_log ${LOG_DIR}/nginx-error.log;

    location / {
        proxy_pass http://${APP_NAME}_backend;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # 超时设置
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }

    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }
}
EOF

    # 启用站点
    ln -sf ${NGINX_CONF} ${NGINX_ENABLED}

    # 测试配置
    nginx -t

    log_success "Nginx 配置创建完成"
}

#-------------------------------------------------------------------------------
# Systemd 服务配置
#-------------------------------------------------------------------------------

create_systemd_service() {
    log_info "创建 Systemd 服务..."

    SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"

    cat > ${SERVICE_FILE} << EOF
[Unit]
Description=Fund QA Agent Service
After=network.target

[Service]
Type=notify
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment="PATH=${VENV_DIR}/bin"
Environment="PYTHONPATH=${APP_DIR}"
ExecStart=${VENV_DIR}/bin/gunicorn api:app \
    --bind 127.0.0.1:${SERVICE_PORT} \
    --workers ${SERVICE_WORKERS} \
    --timeout ${SERVICE_TIMEOUT} \
    --access-logfile ${LOG_DIR}/access.log \
    --error-logfile ${LOG_DIR}/error.log \
    --log-level info
ExecReload=/bin/kill -s HUP \$MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload

    log_success "Systemd 服务创建完成"
}

#-------------------------------------------------------------------------------
# 日志轮转配置
#-------------------------------------------------------------------------------

create_logrotate_config() {
    log_info "创建日志轮转配置..."

    LOGROTATE_CONF="/etc/logrotate.d/${APP_NAME}"

    cat > ${LOGROTATE_CONF} << EOF
${LOG_DIR}/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 ${APP_USER} ${APP_USER}
    sharedscripts
    postrotate
        supervisorctl restart ${APP_NAME} > /dev/null 2>&1 || true
    endscript
}
EOF

    log_success "日志轮转配置创建完成"
}

#-------------------------------------------------------------------------------
# 防火墙配置
#-------------------------------------------------------------------------------

configure_firewall() {
    log_info "配置防火墙..."

    # 检测防火墙类型
    if command -v ufw &> /dev/null; then
        log_info "配置 UFW 防火墙..."
        ufw allow 80/tcp
        ufw allow 443/tcp
        ufw reload
    elif command -v firewall-cmd &> /dev/null; then
        log_info "配置 firewalld..."
        firewall-cmd --permanent --add-port=80/tcp
        firewall-cmd --permanent --add-port=443/tcp
        firewall-cmd --reload
    fi

    log_success "防火墙配置完成"
}

#-------------------------------------------------------------------------------
# 服务启动
#-------------------------------------------------------------------------------

start_services() {
    log_info "启动服务..."

    # 重启 Supervisor
    if command -v supervisorctl &> /dev/null; then
        supervisorctl reread
        supervisorctl update
        supervisorctl restart ${APP_NAME}
    fi

    # 或者使用 Systemd
    if command -v systemctl &> /dev/null; then
        systemctl enable ${APP_NAME}
        systemctl restart ${APP_NAME}
    fi

    # 重启 Nginx
    systemctl restart nginx

    log_success "服务启动完成"
}

#-------------------------------------------------------------------------------
# 健康检查
#-------------------------------------------------------------------------------

health_check() {
    log_info "执行健康检查..."

    sleep 5

    # 检查服务状态
    if curl -sf http://127.0.0.1:${SERVICE_PORT}/health &> /dev/null; then
        log_success "API 服务健康检查通过"
    else
        log_warn "API 服务可能未就绪，请检查日志"
    fi

    # 检查 Nginx
    if systemctl is-active nginx &> /dev/null; then
        log_success "Nginx 运行正常"
    fi

    # 检查端口
    if netstat -tlnp 2>/dev/null | grep -q ":${SERVICE_PORT}"; then
        log_success "端口 ${SERVICE_PORT} 已监听"
    fi
}

#-------------------------------------------------------------------------------
# 部署函数
#-------------------------------------------------------------------------------

deploy() {
    echo "============================================"
    echo "  基金问答智能体 - 自动化部署脚本"
    echo "============================================"
    echo ""

    log_info "开始部署 ${APP_NAME}..."

    check_root
    check_os
    install_system_dependencies
    install_python
    create_directories
    create_virtualenv

    # 复制应用文件
    log_info "复制应用文件..."
    if [[ -f "./main.py" ]]; then
        cp -r . ${APP_DIR}/
    else
        log_error "未找到应用文件，请确保在正确的目录下运行"
        exit 1
    fi

    install_python_dependencies
    create_env_file
    create_supervisor_config
    create_nginx_config
    create_systemd_service
    create_logrotate_config
    configure_firewall
    start_services
    health_check

    echo ""
    echo "============================================"
    log_success "部署完成!"
    echo "============================================"
    echo ""
    echo "访问地址: http://$(hostname -I | awk '{print $1}')/"
    echo "配置目录: ${CONFIG_DIR}"
    echo "日志目录: ${LOG_DIR}"
    echo "数据目录: ${DATA_DIR}"
    echo ""
    echo "常用命令:"
    echo "  查看服务状态: systemctl status ${APP_NAME}"
    echo "  查看日志: tail -f ${LOG_DIR}/access.log"
    echo "  重启服务: systemctl restart ${APP_NAME}"
    echo ""
}

#-------------------------------------------------------------------------------
# 卸载函数
#-------------------------------------------------------------------------------

uninstall() {
    echo "============================================"
    log_warn "即将卸载 ${APP_NAME}..."
    echo "============================================"
    echo ""

    read -p "确定要卸载吗? (yes/no): " confirm

    if [[ "$confirm" != "yes" ]]; then
        log_info "取消卸载"
        exit 0
    fi

    log_info "停止服务..."

    systemctl stop ${APP_NAME} 2>/dev/null || true
    systemctl disable ${APP_NAME} 2>/dev/null || true
    supervisorctl stop ${APP_NAME} 2>/dev/null || true

    log_info "删除文件..."
    rm -rf ${APP_DIR}
    rm -rf ${DATA_DIR}
    rm -rf ${LOG_DIR}
    rm -rf /etc/supervisor/conf.d/${APP_NAME}.conf
    rm -rf /etc/nginx/sites-enabled/${APP_NAME}.conf
    rm -rf /etc/nginx/sites-available/${APP_NAME}.conf
    rm -f /etc/systemd/system/${APP_NAME}.service
    rm -f /etc/logrotate.d/${APP_NAME}

    systemctl daemon-reload
    systemctl restart nginx 2>/dev/null || true
    supervisorctl reload 2>/dev/null || true

    log_success "卸载完成"
}

#-------------------------------------------------------------------------------
# 更新函数
#-------------------------------------------------------------------------------

update() {
    log_info "更新 ${APP_NAME}..."

    # 备份配置
    if [[ -d "${APP_DIR}" ]]; then
        cp -r ${CONFIG_DIR} /tmp/${APP_NAME}-config-backup
        log_info "配置文件已备份"
    fi

    # 更新代码
    if [[ -d ".git" ]]; then
        git pull
    else
        log_error "非 Git 仓库，无法自动更新"
        exit 1
    fi

    # 重新安装依赖
    source ${VENV_DIR}/bin/activate
    pip install -r requirements.txt --upgrade

    # 恢复配置
    if [[ -d "/tmp/${APP_NAME}-config-backup" ]]; then
        cp -r /tmp/${APP_NAME}-config-backup/* ${CONFIG_DIR}/
        rm -rf /tmp/${APP_NAME}-config-backup
    fi

    # 重启服务
    systemctl restart ${APP_NAME}

    log_success "更新完成"
}

#-------------------------------------------------------------------------------
# 查看状态
#-------------------------------------------------------------------------------

status() {
    echo "============================================"
    echo "  ${APP_NAME} 服务状态"
    echo "============================================"
    echo ""

    echo "应用信息:"
    echo "  安装目录: ${APP_DIR}"
    echo "  数据目录: ${DATA_DIR}"
    echo "  日志目录: ${LOG_DIR}"
    echo ""

    echo "服务状态:"
    if command -v systemctl &> /dev/null; then
        systemctl status ${APP_NAME} --no-pager
    fi
    echo ""

    echo "最近日志 (最后 10 行):"
    if [[ -f "${LOG_DIR}/access.log" ]]; then
        tail -n 10 ${LOG_DIR}/access.log
    else
        echo "  无日志文件"
    fi
}

#-------------------------------------------------------------------------------
# 显示帮助
#-------------------------------------------------------------------------------

show_help() {
    cat << EOF
============================================
  基金问答智能体 - 部署管理脚本
============================================

用法: $0 [命令]

命令:
  deploy     部署应用到服务器
  update     更新应用
  uninstall  卸载应用
  status     查看服务状态
  help       显示此帮助信息

示例:
  sudo $0 deploy     # 部署
  sudo $0 update     # 更新
  sudo $0 status     # 查看状态

============================================
EOF
}

#-------------------------------------------------------------------------------
# 主入口
#-------------------------------------------------------------------------------

case "${1:-help}" in
    deploy)
        deploy
        ;;
    update)
        update
        ;;
    uninstall)
        uninstall
        ;;
    status)
        status
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log_error "未知命令: $1"
        show_help
        exit 1
        ;;
esac
