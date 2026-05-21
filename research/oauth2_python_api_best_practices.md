# OAuth2 Best Practices for Python REST APIs

## Executive Summary

OAuth 2.0 is the industry-standard authorization framework for securing REST APIs. This report synthesizes current best practices for implementing OAuth2 in Python REST APIs, covering framework-specific implementations, security considerations, and operational patterns.

---

## 1. Core OAuth2 Concepts

### Key Roles
- **Resource Owner**: The user who owns the data
- **Client**: The application requesting access
- **Authorization Server**: Issues access tokens after authenticating the user
- **Resource Server**: Hosts protected API resources (your API)

### OAuth2 vs JWT
- **OAuth2** is the **authorization framework** — it defines how to delegate access
- **JWT** is a **token format** — often used as the access token in OAuth2 flows
- They work together: OAuth2 provides the flow, JWT provides the stateless, self-contained token format

---

## 2. Python Libraries for OAuth2

### Recommended Libraries by Framework

| Framework | Primary Library | Alternative | Use Case |
|-----------|----------------|-------------|----------|
| **FastAPI** | `fastapi.security` (built-in) | `authlib` | Modern async APIs, auto-generated docs |
| **Flask** | `authlib` | `requests-oauthlib`, `flask-oauthlib` | Traditional web apps, microservices |
| **Django** | `django-oauth-toolkit` | `authlib` | Full-featured Django applications |
| **Generic** | `authlib` | `requests-oauthlib` | Framework-agnostic implementation |

### Key Dependencies
```bash
# FastAPI with JWT
pip install fastapi python-jose[cryptography] passlib[bcrypt] python-multipart

# Flask with Authlib
pip install flask authlib requests

# Django OAuth toolkit
pip install django-oauth-toolkit
```

---

## 3. OAuth2 Flow Selection Guide

### Authorization Code Flow with PKCE ⭐ **RECOMMENDED**
**When to use**: Web applications, SPAs, mobile apps
**Why**: Most secure flow, prevents authorization code interception

```python
# FastAPI implementation pattern
from fastapi.security import OAuth2AuthorizationCodeBearer

oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl="https://auth-server.com/authorize",
    tokenUrl="https://auth-server.com/token",
    refreshUrl="https://auth-server.com/token"
)
```

### Client Credentials Flow
**When to use**: Machine-to-machine (M2M) communication, microservices
**Why**: No user context needed, service-to-service authentication

```python
from fastapi.security import OAuth2ClientCredentialsRequestForm

@app.post("/token")
async def client_credentials_token(form_data: OAuth2ClientCredentialsRequestForm = Depends()):
    # Validate client_id and client_secret
    # Issue access token
    pass
```

### Flows to AVOID

| Flow | Status | Reason |
|------|--------|--------|
| **Implicit Flow** | ❌ Deprecated (OAuth 2.1) | Access tokens exposed in browser, vulnerable to interception |
| **Resource Owner Password** | ❌ Discouraged | Violates OAuth's principle of not sharing credentials |

---

## 4. Token Management Best Practices

### Token Types

#### JWT Access Tokens
**Best for**: Stateless authentication, distributed systems
```python
# JWT structure verification
def create_access_token(data: dict, expires_delta: timedelta):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm="HS256")
```

**Pros**: Self-contained, no database lookups needed
**Cons**: Cannot revoke immediately (must wait for expiration)

#### Opaque Tokens
**Best for**: When immediate revocation is required
**Pros**: Can revoke instantly, smaller token size
**Cons**: Requires token introspection call to authorization server

### Token Lifetimes
- **Access tokens**: 15-60 minutes (short-lived)
- **Refresh tokens**: 7-30 days (with rotation recommended)

### Token Storage Security
- ✅ Use `HttpOnly`, `Secure`, `SameSite=Strict` cookies for web apps
- ✅ Store tokens in secure storage on mobile (Keychain/Keystore)
- ❌ Never store tokens in localStorage (XSS vulnerable)
- ❌ Never expose client secrets in client-side code

---

## 5. Security Considerations

### Essential Security Measures

1. **Always use HTTPS** in production
2. **Validate all JWT claims**:
   - `iss` (issuer) — matches expected authorization server
   - `aud` (audience) — matches your API identifier
   - `exp` (expiration) — token not expired
   - `sub` (subject) — valid user identifier

3. **Implement proper CORS policies**
4. **Use PKCE for all public clients** (SPAs, mobile)
5. **Implement rate limiting** on token endpoints
6. **Use strong signing algorithms** (RS256 preferred over HS256 for distributed systems)

### JWT Validation Pattern (FastAPI)
```python
from jose import JWTError, jwt
from fastapi import HTTPException, status, Depends

async def validate_token(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        # Validate issuer and audience
        if payload.get("iss") != EXPECTED_ISSUER:
            raise credentials_exception
        if payload.get("aud") != EXPECTED_AUDIENCE:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return username
```

### Scope-Based Authorization
```python
from fastapi import Security
from fastapi.security import SecurityScopes

@app.get("/admin/users", dependencies=[Security(validate_token, scopes=["admin:read"])])
async def get_users():
    return {"users": []}
```

---

## 6. Implementation Patterns

### FastAPI Complete Example
```python
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel

app = FastAPI()

# Configuration
SECRET_KEY = "your-secret-key"  # Use environment variable
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

class User(BaseModel):
    username: str
    email: str | None = None
    disabled: bool | None = None

class Token(BaseModel):
    access_token: str
    token_type: str

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    # Retrieve user from database
    user = get_user_from_db(username)
    if user is None:
        raise credentials_exception
    return user

@app.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user
```

---

## 7. User Authentication vs API-to-API

### User Authentication (Authorization Code + PKCE)
- End-user grants permission to application
- Tokens represent user identity
- Used for: Web apps, mobile apps, SPAs

### API-to-API (Client Credentials)
- Service authenticates as itself
- No user context
- Used for: Microservices, background jobs, data pipelines

```python
# Client Credentials implementation
@app.post("/token")
async def client_credentials(
    client_id: str = Form(...),
    client_secret: str = Form(...)
):
    # Validate client credentials
    if not validate_client(client_id, client_secret):
        raise HTTPException(status_code=401, detail="Invalid client credentials")
    
    # Issue token with service scopes
    access_token = create_access_token(
        data={"sub": client_id, "scope": "service:read service:write"}
    )
    return {"access_token": access_token, "token_type": "bearer"}
```

---

## 8. Testing Strategies

### Unit Testing Authentication
```python
# pytest example
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def auth_token():
    # Create a test token
    return create_access_token({"sub": "testuser", "scope": "read"})

def test_protected_endpoint(client, auth_token):
    response = client.get(
        "/protected",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 200

def test_missing_token(client):
    response = client.get("/protected")
    assert response.status_code == 401

def test_invalid_token(client):
    response = client.get(
        "/protected",
        headers={"Authorization": "Bearer invalid_token"}
    )
    assert response.status_code == 401
```

### Integration Testing with OAuth Providers
- Use OAuth2 test/sandbox environments
- Mock external authorization servers in unit tests
- Use tools like `pytest-oauth2client` for testing OAuth flows

---

## 9. Authorization Servers

### Managed Solutions (Recommended for Production)
| Provider | Best For | Features |
|----------|----------|----------|
| **Auth0** | Rapid development, enterprise features | Universal login, MFA, social providers |
| **Keycloak** | Self-hosted, on-premise requirements | Open source, full feature set |
| **AWS Cognito** | AWS ecosystem integration | Serverless, scalable, good pricing |
| **Okta** | Enterprise SSO | Comprehensive identity management |

### Self-Hosted Options
- **Keycloak**: Full-featured, Java-based
- **ORY Hydra**: Cloud-native, Go-based
- **IdentityServer4** (deprecated, migrating to Duende)

---

## 10. OAuth 2.1 Updates

Key changes in OAuth 2.1 (current draft):
- PKCE is **required** for all public clients
- Implicit flow is **removed**
- Password grant is **removed**
- Refresh tokens for public clients must be sender-constrained or one-time use

**Recommendation**: Implement OAuth 2.1 patterns now for future-proofing.

---

## 11. Quick Reference Checklist

### Implementation Checklist
- [ ] Use HTTPS everywhere in production
- [ ] Implement proper token validation (signature, claims, expiration)
- [ ] Use short-lived access tokens (15-60 min)
- [ ] Implement refresh token rotation
- [ ] Store secrets securely (environment variables, vaults)
- [ ] Use PKCE for all public clients
- [ ] Implement proper error responses (401, 403 distinction)
- [ ] Add rate limiting to token endpoints
- [ ] Log authentication events for security monitoring
- [ ] Test token expiration and refresh flows

---

## Sources

1. FastAPI Security Documentation — https://fastapi.tiangolo.com/tutorial/security/
2. OAuth 2.0 Simplified — Aaron Parecki
3. Authlib Documentation — https://docs.authlib.org/
4. OWASP OAuth 2.0 Cheat Sheet
5. RFC 6749 — The OAuth 2.0 Authorization Framework
6. RFC 7636 — Proof Key for Code Exchange (PKCE)

---

*Report generated: May 2024*
