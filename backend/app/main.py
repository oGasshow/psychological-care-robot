"""FastAPI 主应用"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import engine, Base
from .routers import auth, chat, assessment, training, diary, growth, analytics
from . import robot_records
from .care import api as care_api
from .voice import api as voice_api
from . import care_management
from .deployment import role
from .care.settings import engine_configuration
engine_configuration()

# 创建数据库表
Base.metadata.create_all(bind=engine)
from .voice.collection_plan import backfill_recent_plans
if role() != 'central':
    backfill_recent_plans()

# 创建 FastAPI 应用
app = FastAPI(
    title="心理疏导机器人系统 API",
    description="心理健康陪伴助手后端 API",
    version="1.0.0"
)

# 配置 CORS（允许前端跨域请求）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js 开发服务器
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(assessment.router)
app.include_router(training.router)
app.include_router(diary.router)
app.include_router(growth.router)
app.include_router(analytics.router)
app.include_router(robot_records.router)
robot_records.install_handlers(app)
care_api.install(app)
voice_api.install(app)
care_management.install(app)

@app.middleware('http')
async def deployment_boundary(request, call_next):
    from fastapi.responses import JSONResponse
    path = request.url.path
    if role() == 'central' and path.startswith('/api/'):
        allowed = (path in ('/api/auth/login', '/api/auth/me', '/api/deployment') or
                   (request.method == 'GET' and path.startswith('/api/care-management/')))
        if not allowed:
            return JSONResponse(status_code=403, content={'detail':'当前服务仅提供管理员登录和报告读取。'})
    if role() == 'edge' and path.startswith('/api/care-management'):
        return JSONResponse(status_code=403, content={'detail':'请使用服务器的报告管理入口。'})
    return await call_next(request)

@app.get('/api/deployment')
async def deployment_info():
    return {'role':role()}

# 根路径
@app.get("/")
async def root():
    """API 根路径"""
    return {
        "message": "心理疏导机器人系统 API",
        "version": "1.0.0",
        "status": "running"
    }

# 健康检查
@app.get("/health")
def health_check():
    """健康检查端点"""
    if role() in ('edge','central'):
        from sqlalchemy import text
        from fastapi.responses import JSONResponse
        try:
            with engine.connect() as db:
                db.execute(text('SELECT 1'))
        except Exception:
            return JSONResponse(status_code=503,content={'status':'unavailable','storage':'server_unavailable'})
        return {'status':'healthy','role':role(),'storage':'server-postgresql'}
    return {"status": "healthy"}
