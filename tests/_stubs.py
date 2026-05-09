from __future__ import annotations

import sys
import types


def install_dependency_stubs() -> None:
    if "fastapi" not in sys.modules:
        module = types.ModuleType("fastapi")

        class FastAPI:
            def __init__(self, *args, **kwargs) -> None:
                self.args = args
                self.kwargs = kwargs

            def include_router(self, *_args, **_kwargs) -> None:
                return None

            def get(self, *_args, **_kwargs):
                def decorator(fn):
                    return fn

                return decorator

        class APIRouter:
            def get(self, *_args, **_kwargs):
                def decorator(fn):
                    return fn

                return decorator

            def post(self, *_args, **_kwargs):
                def decorator(fn):
                    return fn

                return decorator

            def websocket(self, *_args, **_kwargs):
                def decorator(fn):
                    return fn

                return decorator

        class HTTPException(Exception):
            def __init__(self, status_code: int, detail: str) -> None:
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail

        class WebSocket:
            pass

        class Request:
            async def body(self) -> bytes:
                return b""

        def Header(*_args, **kwargs):
            return kwargs.get("default")

        module.FastAPI = FastAPI
        module.APIRouter = APIRouter
        module.HTTPException = HTTPException
        module.Request = Request
        module.WebSocket = WebSocket
        module.Header = Header
        sys.modules["fastapi"] = module

    if "fastapi.responses" not in sys.modules:
        module = types.ModuleType("fastapi.responses")

        class FileResponse:
            def __init__(self, path, media_type=None, filename=None) -> None:
                self.path = path
                self.media_type = media_type
                self.filename = filename

        class StreamingResponse:
            def __init__(self, content, media_type=None, headers=None, status_code=200) -> None:
                self.body_iterator = content
                self.media_type = media_type
                self.headers = headers or {}
                self.status_code = status_code

        module.FileResponse = FileResponse
        module.StreamingResponse = StreamingResponse
        sys.modules["fastapi.responses"] = module

    if "pydantic_settings" not in sys.modules:
        module = types.ModuleType("pydantic_settings")

        class BaseSettings:
            def __init__(self, **kwargs) -> None:
                for name, value in self.__class__.__dict__.items():
                    if name.startswith("_") or callable(value) or isinstance(value, property):
                        continue
                    setattr(self, name, kwargs.get(name, value))

        def SettingsConfigDict(**kwargs):
            return kwargs

        module.BaseSettings = BaseSettings
        module.SettingsConfigDict = SettingsConfigDict
        sys.modules["pydantic_settings"] = module

    if "redis" not in sys.modules:
        module = types.ModuleType("redis")

        class Redis:
            @classmethod
            def from_url(cls, _url: str):
                return cls()

            def ping(self) -> bool:
                return True

        module.Redis = Redis
        sys.modules["redis"] = module

    if "rq" not in sys.modules:
        module = types.ModuleType("rq")

        class Queue:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def enqueue(self, *_args, **_kwargs) -> None:
                return None

        module.Queue = Queue
        sys.modules["rq"] = module

    if "openai" not in sys.modules:
        module = types.ModuleType("openai")
        module.OpenAI = object
        sys.modules["openai"] = module

    if "requests" not in sys.modules:
        module = types.ModuleType("requests")
        module.post = lambda *args, **kwargs: None
        module.get = lambda *args, **kwargs: None
        sys.modules["requests"] = module

    if "httpx" not in sys.modules:
        module = types.ModuleType("httpx")
        module.post = lambda *args, **kwargs: None
        module.get = lambda *args, **kwargs: None
        sys.modules["httpx"] = module

    if "faiss" not in sys.modules:
        module = types.ModuleType("faiss")
        module.read_index = lambda *_args, **_kwargs: None
        sys.modules["faiss"] = module

    if "jieba" not in sys.modules:
        module = types.ModuleType("jieba")
        module.cut = lambda text: text.split()
        sys.modules["jieba"] = module

    if "numpy" not in sys.modules:
        module = types.ModuleType("numpy")
        module.ndarray = object
        module.float32 = "float32"
        module.asarray = lambda values, dtype=None: values
        module.zeros = lambda shape, dtype=None: [[0.0 for _ in range(shape[1])] for _ in range(shape[0])]
        module.min = min
        module.max = max
        module.linalg = types.SimpleNamespace(norm=lambda _value: 0.0)
        sys.modules["numpy"] = module

    if "rank_bm25" not in sys.modules:
        module = types.ModuleType("rank_bm25")

        class BM25Okapi:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def get_scores(self, _tokens):
                return []

        module.BM25Okapi = BM25Okapi
        sys.modules["rank_bm25"] = module
