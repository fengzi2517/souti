"""全局配置：环境变量驱动，生产/开发仅改 .env"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    # 数据层
    database_url: str = "postgresql+asyncpg://solve:solve123@localhost:5434/ai_solve"
    redis_url: str = "redis://localhost:6379/0"

    # LLM（OpenAI 兼容）
    llm_base_url: str = "https://token.sensenova.cn/v1"
    llm_api_key: str = ""
    llm_model: str = "sensenova-6.8-flash-lite"
    llm_timeout: int = 180  # 视觉直传（大图+推理+长输出）需要 2~3 分钟，不能设 60s
    llm_max_tokens: int = 32768  # reasoning 模型思考+输出都要空间；实测 glm-5.2 视觉解析偶发思考超 16k 被截断
    # 视觉（图片直传）专用模型：必须是网关上支持 image 输入的多模态模型。
    # 实测 sensenova-6.8-flash-lite 可正确读图；glm-5.2 / deepseek-v4 为纯文本模型，
    # 传入图片会被静默忽略并幻觉作答（自称图里是 LIFE IS LIKE A BOX OF CHOCOLATES）。
    llm_vision_model: str = "sensenova-6.8-flash-lite"

    # 业务
    rate_limit_daily: int = 200
    upload_dir: Path = BASE_DIR / "uploads"
    max_image_size: int = 10 * 1024 * 1024  # 10MB

    # 跨域：逗号分隔的 origin 列表；生产改为真实域名（如 https://xxx.com）
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # 反向代理：部署在 Nginx/网关后置 true，限流才取 X-Forwarded-For 里的真实客户端 IP。
    # 直连暴露或本地开发保持 false——否则客户端可伪造头绕过 IP 限流。
    trust_proxy: bool = False

    # JWT（M2 登录体系）。默认值仅开发用（>=32 字节满足 HS256 推荐），生产必须覆盖
    jwt_secret: str = "dev-secret-change-in-production!!"
    jwt_expire_hours: int = 720  # 30 天
    sms_dev_mode: bool = True  # 开发模式：不发真短信，验证码固定 123456 并直接返回

    # OCR 引擎：auto（默认，优先 RapidOCR、回退 Paddle）/ rapidocr / paddle。
    # RapidOCR=onnxruntime CPU 推理，密集大图实测 ~6s（Paddle 同图 ~450s），模型打包在包内；
    # PaddleOCR 精度略稳但 CPU 慢，且本机 oneDNN 有 PIR bug 必须关 MKLDNN。
    ocr_engine: str = "auto"
    # PaddleOCR 模型缓存目录（仅引擎为 paddle 时用；RapidOCR 模型在包内无需缓存）
    paddle_cache_dir: str = r"D:\Users\3392\.paddlex"

    # 缓存 TTL（秒）
    cache_ttl_solve: int = 7 * 24 * 3600
    cache_ttl_ocr: int = 7 * 24 * 3600

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS_ORIGINS（逗号分隔字符串）解析为列表。"""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
