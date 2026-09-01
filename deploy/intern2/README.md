# intern2 用户级部署

目标环境：Ubuntu 24.04，用户 `intern2`，无 sudo、无 Docker socket 权限。

## 目录与端口

- 项目目录：`/home/intern2/projects/disney-voice-assistant`
- Python 虚拟环境：项目内 `.venv`
- 日志：项目内 `data/logs/server.log`
- 默认监听：`0.0.0.0:18124`
- PID 文件：项目内 `data/run/disney_voice.pid`

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
curl http://127.0.0.1:18124/healthz
```

查看日志：

```bash
tail -f data/logs/server.log
```

服务器没有安装 `screen`，启动脚本使用 `nohup` 和 PID 文件托管进程，不需要 sudo。

## 公网限制

脚本不修改 nginx、防火墙或系统服务。应用由 `intern2` 普通用户直接监听 `18124`，不需要 sudo 或 Docker 权限。
