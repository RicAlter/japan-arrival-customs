"""Local trusted-administrator session adapter, not a WorkBuddy login service.

Only root/security/trusted_sessions.json is consulted. Neither workbook nor request
payload supplies actor/roles. The host must protect this directory from upload writers.
"""
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .core import Rejected, digest, now, require_actor
from .contracts import effective_permissions

_SEAL = object()


@dataclass(frozen=True)
class Session:
    principal: str
    roles: tuple
    mode: str
    credential_ref: str
    expires_at: str
    root: str
    config_hash: str
    _token_hash: str = field(repr=False)
    _seal: object = field(repr=False)

    def evidence(self):
        return {'principal': self.principal, 'roles': list(self.roles), 'mode': self.mode,
                'credential_ref': self.credential_ref, 'config_hash': self.config_hash}


def load_session(root, token):
    root = Path(root).resolve()
    path = root/'security/trusted_sessions.json'
    if not isinstance(token, str) or not token:
        raise Rejected('需要可信执行会话，不能从Excel取得身份')
    try:
        config = json.loads(path.read_text(encoding='utf-8'))
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        entry = next((x for x in config['sessions'] if hmac.compare_digest(x['token_sha256'], token_hash)), None)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise Rejected('可信会话配置不可用；实际D08尚未配置时不得审核') from exc
    if not entry or entry.get('mode') not in ('business', 'synthetic_technical_test'):
        raise Rejected('无效的可信执行会话')
    try:
        expires = datetime.fromisoformat(entry['expires_at'])
        if expires.tzinfo is None or expires <= datetime.now(timezone.utc): raise ValueError()
        if not entry['principal'].strip() or not entry['credential_ref'].strip(): raise ValueError()
        if not isinstance(entry['roles'], list) or any(not isinstance(r,str) for r in entry['roles']): raise ValueError()
    except (KeyError, ValueError, TypeError) as exc:
        raise Rejected('会话已过期或身份凭据不完整') from exc
    return Session(entry['principal'], tuple(entry['roles']), entry['mode'], entry['credential_ref'],
                   entry['expires_at'], str(root), digest(config), token_hash, _SEAL)


def validate_session(root, session, execution_mode):
    if not isinstance(session, Session) or session._seal is not _SEAL or session.root != str(Path(root).resolve()):
        raise Rejected('禁止请求数据伪造可信执行身份')
    try:
        config = json.loads((Path(root)/'security/trusted_sessions.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise Rejected('可信配置读取失败') from exc
    if digest(config) != session.config_hash or datetime.fromisoformat(session.expires_at) <= datetime.now(timezone.utc):
        raise Rejected('可信会话已失效或权限配置已变化')
    if session.mode == 'synthetic_technical_test' and execution_mode != session.mode:
        raise Rejected('合成权限只能用于明确标记的技术测试批次')
    if session.mode == 'business' and execution_mode == 'synthetic_technical_test':
        raise Rejected('技术测试批次不能升级为真实业务审核')


def authorize(root, session, batch, role):
    from .business_setup import require_contract, require_managed_review
    require_contract(batch)
    validate_session(root,session,batch.get('execution_mode'))
    if batch.get('runtime_context'):
        require_managed_review(root,batch)
    permissions = effective_permissions(batch, {session.principal: list(session.roles)})
    require_actor(session.principal, role, permissions)
    return permissions
