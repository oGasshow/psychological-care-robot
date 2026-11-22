"""认证相关路由"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User
from ..schemas import UserRegister, UserLogin, Token, UserResponse, Response
from ..auth import verify_password, get_password_hash, create_access_token, get_current_user
from ..care_management import can_manage_reports

router = APIRouter(prefix="/api/auth", tags=["认证"])

@router.post("/register", response_model=Response, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """用户注册"""
    # 检查用户名是否已存在
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已被注册"
        )
    
    # 创建新用户
    hashed_password = get_password_hash(user_data.password)
    new_user = User(
        username=user_data.username,
        hashed_password=hashed_password
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return Response(
        success=True,
        message="注册成功",
        data={"user_id": new_user.id, "username": new_user.username}
    )

@router.post("/login", response_model=Token)
async def login(user_data: UserLogin, db: Session = Depends(get_db)):
    """用户登录"""
    # 查找用户
    user = db.query(User).filter(User.username == user_data.username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    
    # 验证密码
    if not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    
    # 检查用户是否被禁用
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用"
        )
    from ..deployment import role
    manager = can_manage_reports(db, user.id)
    if role() == 'central' and not manager:
        raise HTTPException(status_code=403, detail='此入口仅供管理员登录，请在终端使用用户账号。')
    if role() == 'edge' and manager:
        raise HTTPException(status_code=403, detail='请在服务器管理员入口登录。')
    
    # 生成 JWT token
    access_token = create_access_token(data={"sub": user.username})
    
    return Token(access_token=access_token)

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取当前登录用户信息"""
    return dict(id=current_user.id, username=current_user.username, created_at=current_user.created_at,
                is_active=current_user.is_active, can_manage_reports=can_manage_reports(db, current_user.id))
