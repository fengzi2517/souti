# AI 解题助手（souti）

拍照 / 截图 / 粘贴 / 文字输入题目，AI 给出答案与分步解析，围绕该题提供复盘归纳、举一反三变式训练、AI 批改讲评与错题本闭环。全栈单仓库：Vue 3 前端 + FastAPI 后端 + PostgreSQL / Redis。

- 图片输入：双引擎 OCR 识别，或跳过 OCR 把图直接交给视觉模型解析
- 分步解析：任务轮询架构，进度可见，reasoning 模型 15~60s 的解析不受连接超时影响
- 举一反三：同考点变式训练（基础 / 进阶 / 挑战），作答后 AI 批改讲评并归类错因
- 错题本闭环：错题自动入本，支持筛选 / 重练；搜题历史按账号云端同步
- 手机验证码登录（JWT 30 天）+ 游客模式，游客数据在登录时自动并入账号

本仓库不含任何 API Key、真实手机号或用户数据；`.env`、上传图片、本地运行产物均被 .gitignore 排除（见第十节）。

## 一、能力概览

- 双输入通道：上传图片（长边 >2048 或体积 >1MB 自动压缩为长边 2048 / JPEG 85）或直接输入文字题干
- OCR 双引擎：RapidOCR（onnxruntime，默认，密集大图约 6s）/ PaddleOCR（备选，`OCR_ENGINE` 切换，可选依赖），子进程隔离 + 信号量限并发，引擎未安装时走文字输入兜底
- 解析结构化：答案、分步解析（LaTeX）、考点、易错点、知识点卡片，按学段三档（小学 / 初中 / 高中）分流 system prompt
- 同题秒回：解析与 OCR 结果按内容哈希缓存 7 天，命中直接返回，不重复调用 LLM
- 任务轮询：`POST /api/solve` 校验 + 限流后立即返回 task_id，前端 2s 轮询分阶段进度（读题 → 推理 → 书写解析），任何异常兜底为 failed，不会永久 pending
- 变式训练与批改：每题生成三档难度变式集（缓存 7 天，`refresh=true` 换一套），提交作答后逐题批改讲评、归类错因、错题自动入本
- 成本审计：解析 / 出题 / 批改消耗的 tokens 全量落库，可按用户、按日汇总核算
- 运维可观测：`/api/health` 返回 DB / Redis 探活 + OCR 队列深度；request_id 贯穿日志并经 `X-Request-ID` 回传

## 二、技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + Vite + TypeScript + Pinia + Vue Router + KaTeX |
| 后端 | Python 3.12+ / FastAPI + SQLAlchemy 2.0 (async) + Pydantic v2 |
| 数据 | PostgreSQL 16 + Redis 7（docker-compose，仅绑 127.0.0.1） |
| LLM | OpenAI 兼容接口（默认 SenseNova `sensenova-6.8-flash-lite`，可切 DeepSeek 等） |
| OCR | RapidOCR 3.9.2（onnxruntime）/ PaddleOCR 3.3.3（可选依赖 `requirements-ocr.txt`） |
| 迁移 | Alembic（async；0001 基线 + 0002 tokens / 复合索引） |
| 测试 | pytest（70 用例，临时 SQLite，不碰开发库） |
| 部署 | docker-compose（数据层）+ uvicorn（API）+ Nginx 托管前端 dist |

## 三、架构设计

### 3.1 顶层数据流

```text
浏览器 (Vue 3, :5173)
   │  上传图片 / 文字题干 / 轮询任务
   ▼
FastAPI (:8000)
   ├─ upload   ：压缩 + 路径穿越防护 → 本地 uploads/
   ├─ solve    ：查缓存 ──命中──→ 直接返回 question_id
   │             未命中 → 立即返回 task_id，后台任务执行
   │             OCR(子进程) → LLM(OpenAI 兼容) → JSON 校验 → 带反馈重试
   ├─ tasks    ：GET /api/tasks/{id}，前端 2s 轮询分阶段进度
   ├─ practice ：变式生成 → 作答提交 → AI 批改讲评
   └─ auth/records ：验证码登录(JWT) / 错题本 / 搜题历史
   ▼
PostgreSQL (:5434)  题目 / 解析 / 练习 / 错题 / 历史
Redis (:6379)       缓存 + 限流 + 任务状态（断连自动降级进程内存）
```

### 3.2 模块职责

| 模块 | 关键文件 | 职责 |
|---|---|---|
| 入口 | `app/main.py` | 应用组装、CORS、request_id 日志、uploads 定期清理、`/api/health` |
| 配置 | `app/config.py` | 全部环境变量（.env 驱动，开发 / 生产零代码差异） |
| 数据层 | `app/db.py`、`app/models.py` | async engine / session、8 张表与复合索引 |
| 契约 | `app/schemas.py` | Pydantic 请求 / 响应模型 |
| 认证 | `app/auth.py` | Identity 依赖（user_id / client_id 双轨）、`owns()` 归属过滤、JWT |
| LLM | `app/ai/client.py`、`prompts.py`、`pipeline.py` | OpenAI 兼容客户端（JSON 容错提取 + LLMError 分类）、按学段三档 prompt、生成 → 校验 → 带反馈重试 |
| OCR | `app/ai/ocr.py` | 双引擎子进程封装、asyncio 信号量限并发、队列深度上报 |
| 缓存 | `app/services/cache.py` | Redis 缓存 + 限流 + 任务存储，断连降级内存并周期重连 |
| 路由 | `app/routers/*.py` | auth / upload / solve / practice / records 五组路由 |
| 前端 | `frontend/src/*` | 8 个页面、Pinia 登录态、KaTeX 渲染（失败降级转义）、axios 封装 + 401 拦截 + 任务轮询 |

### 3.3 关键技术决策

- 任务轮询替代 SSE / 长连接：reasoning 模型解析需 15~60s，长连接会被代理超时切断且无进度反馈；代价是任务状态需 TTL 管理（1h）与前端 2s 轮询
- OpenAI 兼容接口替代绑定单一厂商 SDK：换模型只改 .env 三个变量，缓存 key 含模型名、换模型自动隔离旧缓存；代价是需要自己做 JSON 容错提取与截断反馈重试
- Redis 断连降级进程内存而非直接报错：可用性优先，60s 冷却后自动重连，业务零中断；代价是内存模式不跨进程、重启即失
- OCR 放在子进程并用信号量限并发：onnxruntime / paddle 原生库崩溃不会拖垮事件循环；代价是子进程启动开销与可选依赖管理
- 游客 client_id 与登录 user_id 双轨归属：免登录即可用，登录时数据自动并入账号；代价是所有列表 / 详情接口必须经 `owns()` 双键过滤
- singleflight 进程内去重：并发同题只跑一次 LLM；代价是当前为单 worker 语义，多实例部署需换 Redis 分布式锁

## 四、核心机制

### 4.1 解析任务轮询

```text
POST /api/solve      → 校验 + 限流 + 查缓存
                       命中 → 返回 question_id（秒回）
                       未命中 → 写任务状态(pending) → 返回 task_id
后台任务             → OCR → LLM 解析 → 结构化入库 → 状态置 done
GET /api/tasks/{id}  → 前端 2s 轮询：running（阶段话术）/ done / failed
异常兜底             → 任一步失败即置 failed 并给出原因，不会永久 pending
```

### 4.2 LLM 生成管线

生成 → JSON 解析 → 字段级校验 → 失败则把错误信息拼回 prompt 重试（全局最多 2 次 LLM 调用）。截断、缺字段、非 JSON 分别归类为 LLMError 子类；重试仍失败返回 422，不落脏数据。reasoning 模型的 `LLM_MAX_TOKENS` 需给足（默认 32768），否则思考占用预算导致输出截断。

### 4.3 数据归属与登录安全

- Identity：登录态按 `user_id`（跨设备可见），游客按 `client_id`（仅本设备），登录时游客数据自动并入账号
- 所有列表 / 详情接口经 `owns()` 过滤，越权访问一律 404（不暴露资源是否存在）
- 验证码错误 5 次锁 15 分钟；短信 1 条 / 分钟、5 条 / 天；比较用 `hmac.compare_digest` 防时序侧信道
- 非开发模式（`SMS_DEV_MODE=false`）下仍保持默认 `JWT_SECRET` 时，启动即拒绝（fail-fast）

### 4.4 缓存与降级

- 解析 / OCR 结果按内容哈希缓存 7 天（`CACHE_TTL_SOLVE` / `CACHE_TTL_OCR`）；变式题集缓存 7 天，`refresh=true` 强制重新生成
- Redis 探测失败 → 自动切换进程内存实现（同一套接口），60s 冷却后重连；内存模式定期清扫过期项防泄漏
- 限流：每用户 / 每 IP 每日 200 次（`RATE_LIMIT_DAILY`），网关后部署置 `TRUST_PROXY=true` 才取 `X-Forwarded-For` 真实 IP

### 4.5 磁盘治理与成本观测

- 后台任务每 6h 删除超 7 天且未被任何 Question 引用的上传图片，防磁盘无限增长
- `questions.tokens`（解析）、`practice_sets.tokens_gen / tokens_grade`（出题 / 批改）全量落库，可按用户、按日核算 LLM 成本

## 五、数据库 Schema

| 表 | 用途 |
|---|---|
| users | 手机号登录账号 |
| questions | 题目：题干、图片路径与哈希、学科、学段、状态、解析 tokens |
| solutions | 解析结果：步骤 JSON、答案、考点、易错点、知识点卡片、模型名、tokens |
| practice_sets | 变式练习集：状态（created / submitted）、生成与批改 tokens 审计 |
| practice_items | 单道变式题：难度、题干、标准答案（作答前不下发）、作答、批改结果、错因 |
| mistakes | 错题本：归属双键 + created_at 复合索引，来源（变式 / 手动） |
| histories | 搜题历史：归属双键 + viewed_at 复合索引 |
| knowledge_points | 知识点字典（父子层级，供解析页卡片） |

## 六、仓库结构

```text
backend/
  app/
    config.py            环境变量配置（.env）
    db.py  models.py     async 数据层：8 张表 + 复合索引
    schemas.py           API 契约（Pydantic）
    auth.py              Identity 依赖 + owns() 归属过滤 + JWT
    main.py              应用入口：日志 / 清理任务 / 健康检查
    ai/
      client.py          LLM 客户端（JSON 容错提取 + LLMError 分类）
      prompts.py         按学段三档 prompt（解析 / 变式 / 批改）
      pipeline.py        生成 → 校验 → 带反馈重试
      ocr.py             OCR 双引擎子进程封装 + 并发控制
    services/cache.py    Redis 缓存 + 限流 + 任务存储（降级内存 + 自动重连）
    routers/             auth / solve / upload / practice / records
  migrations/            Alembic（0001 基线，0002 tokens + 索引）
  tests/                 pytest 70 用例（临时 SQLite）
  requirements*.txt      运行 / 开发 / OCR 可选依赖
frontend/
  src/views/             8 个页面（首页 / 确认 / 解析 / 做题 / 批改 / 错题本 / 历史 / 登录）
  src/stores/auth.ts     Pinia 登录态
  src/api.ts             axios 封装 + 401 拦截 + 任务轮询
  src/latex.ts           $...$ LaTeX + **粗体** 渲染（KaTeX，失败降级转义）
docker-compose.yml       PG(127.0.0.1:5434) + Redis(127.0.0.1:6379)
start-backend.bat / start-frontend.bat   Windows 一键启动
```

## 七、最快本地启动

### 7.1 依赖

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt -r requirements-dev.txt
# 需要 OCR 时再装可选依赖（RapidOCR 默认随主依赖可用）：
# .venv/Scripts/python.exe -m pip install -r requirements-ocr.txt
```

### 7.2 数据层

```bash
docker compose up -d        # PG :5434 + Redis :6379，仅绑 127.0.0.1
```

### 7.3 配置 backend/.env

| 变量 | 默认 | 说明 |
|---|---|---|
| `LLM_API_KEY` | （空） | 必填，OpenAI 兼容平台的 Key |
| `LLM_BASE_URL` | `https://token.sensenova.cn/v1` | 换 DeepSeek 等平台改这里 |
| `LLM_MODEL` | `sensenova-6.8-flash-lite` | 模型名；缓存 key 含模型名，换模型自动隔离旧缓存 |
| `LLM_VISION_MODEL` | 同上 | 图片直传用的多模态模型（必须是支持 image 输入的模型） |
| `DATABASE_URL` | `postgresql+asyncpg://solve:solve123@127.0.0.1:5434/ai_solve` | 用 `127.0.0.1` 而非 `localhost`（避免 IPv6 解析挂起） |
| `REDIS_URL` | `redis://localhost:6379/0` | 生产加密码 |
| `JWT_SECRET` | `dev-secret-...` | 生产必改为 ≥32 字节随机串；保持默认且非开发模式时拒绝启动 |
| `SMS_DEV_MODE` | `true` | 开发模式验证码固定 `123456` 并回显；接真实短信后置 `false` |
| `CORS_ORIGINS` | `http://localhost:5173,...` | 逗号分隔；生产改为真实域名 |
| `OCR_ENGINE` | `auto` | auto / rapidocr / paddle |

### 7.4 数据库迁移

```bash
cd backend && .venv/Scripts/python.exe -m alembic upgrade head
```

### 7.5 启动后端（:8000）

```bash
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# API 文档: http://127.0.0.1:8000/docs
```

### 7.6 启动前端（:5173）

```bash
cd ../frontend
npm install        # 首次
npm run dev        # http://localhost:5173，已配置 /api 代理到 :8000
```

Windows 下也可直接双击根目录 `start-backend.bat` 与 `start-frontend.bat`。

## 八、测试

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests -q     # 70 用例：API 冒烟 / 认证 / 缓存 / 管线 / 上传安全等
```

测试自动使用临时 SQLite，不依赖 PG / Redis，也不碰开发库。

## 九、部署

- `JWT_SECRET` 换 ≥32 字节随机串；`CORS_ORIGINS` 改真实前端域名；`SMS_DEV_MODE=false` 并接入真实短信通道
- Nginx / 网关后部署置 `TRUST_PROXY=true`（否则限流按代理 IP 计）；Redis 与 PG 改强密码并同步连接串
- `alembic upgrade head`；前端 `npm run build` 后由 Nginx 托管 `dist/`
- 多 worker 部署前先确认 singleflight 的进程内锁语义（当前单 worker；多实例需换 Redis 分布式锁）

## 十、不提交的内容

以下本地文件 / 目录被 .gitignore 排除，仓库中不存在：

- `backend/.env` —— 所有密钥与环境配置（仅文档化变量表，见 7.3）
- `backend/uploads/` —— 用户上传图片（含 7 天自动清理）
- `backend/.venv/`、`frontend/node_modules/`、`frontend/dist/` —— 依赖与构建产物
- 日志与本地调试产物：`*.log`、`backend/solve_test.json`、`backend/qid.txt`、`backend/test_question.png`
- `shots/`、`.workbuddy/` 等本地工作目录
