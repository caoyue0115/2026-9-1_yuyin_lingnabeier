# intern2 用户级部署

目标环境：Ubuntu 24.04，用户 `intern2`，无 sudo、无 Docker socket 权限。

## 目录与端口

- 项目目录：`/home/intern2/projects/disney-voice-assistant`
- Python 虚拟环境：项目内 `.venv`
- 日志：项目内 `data/logs/server.log`
- 默认监听：`0.0.0.0:18120`
- screen 会话：`disney_voice`

## 首次安装

```bash
cd /home/intern2/projects/disney-voice-assistant
bash deploy/intern2/bootstrap.sh
cp .env.example .env
```

然后由用户把 `DASHSCOPE_API_KEY` 写入 `.env`。取得热词 ID 和朱迪 voice ID 后，再分别填写 `ASR_VOCABULARY_ID` 与 `REALTIME_TTS_VOICE`。

## 启动与检查

```bash
bash deploy/intern2/start.sh
bash deploy/intern2/status.sh
curl http://127.0.0.1:18120/healthz
```

查看日志：

```bash
tail -f data/logs/server.log
```

进入 screen：

```bash
screen -r disney_voice
```

使用 `Ctrl+A`、再按 `D` 可退出 screen 而不停止服务。

## 公网限制

脚本不修改 nginx、防火墙或系统服务。如果 `18120` 只能在服务器本机访问，需要管理员只处理端口放行或 nginx 反向代理；应用本身仍以 `intern2` 普通用户运行。
