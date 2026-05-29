from typing import List, Optional

from pydantic import BaseModel


class SourceItem(BaseModel):
    name: str
    rerank_score: float
    text: str = ""


class CharacterItem(BaseModel):
    id: int
    name: str


class ChatRequest(BaseModel):
    query: str
    session_id: str = "default"
    character_name: str
    chat_mode: str = "offline"
    conversation_title: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    character: Optional[str]
    sources: List[SourceItem]
    session_id: str
    long_term_history_count: int
    short_term_history_count: int


class ClearRequest(BaseModel):
    session_id: str = "default"
    conversation_title: Optional[str] = None
    character_name: Optional[str] = None
    chat_mode: str = "offline"


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    confirm_password: str


class LoginRequest(BaseModel):
    account: str
    password: str


class AuthResponse(BaseModel):
    success: bool
    message: str
    token: Optional[str] = None
    user: Optional[dict] = None


class UserAdminUpdateRequest(BaseModel):
    is_admin: bool
