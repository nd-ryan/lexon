# Streaming Setup Guide

This guide explains how to set up the secure JWT-based streaming authentication system that allows the frontend to connect directly to the backend for long-running search operations.

## 🔒 Security Architecture

The system uses JWT tokens to authenticate streaming connections while keeping sensitive credentials secure:

1. **Frontend** → **Vercel API** (gets JWT token)
2. **Frontend** → **Fly.io Backend** (direct connection with JWT)

This eliminates Vercel's 60-second timeout limitations while maintaining security.

## 📋 Environment Variables Setup

### Frontend (.env.local)
```env
# Required for JWT token generation
JWT_SECRET="your-secure-jwt-secret-here"

# Backend URL (used by Vercel API to provide to frontend)
AI_BACKEND_URL="https://your-backend.fly.dev"

# Existing variables
NEXTAUTH_SECRET="your-nextauth-secret"
FASTAPI_API_KEY="your-api-key"
```

### Backend (.env)
```env
# Must match frontend JWT_SECRET exactly
JWT_SECRET="your-secure-jwt-secret-here"

# Existing variables
FASTAPI_API_KEY="your-api-key"
REDIS_URL="redis://localhost:6379"
NEO4J_URI="bolt://localhost:7687"
# ... other variables
```

### Vercel Environment Variables
In your Vercel dashboard, add:
- `JWT_SECRET` (same value as local)
- `AI_BACKEND_URL` (your Fly.io backend URL)

## 🚀 How It Works

### 1. Job Enqueueing (Quick Operation)
```typescript
// Still goes through Vercel API for security
const response = await fetch('/api/search/crew/stream', {
  method: 'POST',
  body: JSON.stringify({ query })
});
const { job_id } = await response.json();
```

### 2. Token Generation (Secure)
```typescript
// Get JWT token from Vercel API
const tokenResponse = await fetch('/api/auth/stream-token', {
  method: 'POST',
  body: JSON.stringify({ jobId: job_id })
});
const { token, backendUrl } = await tokenResponse.json();
```

### 3. Direct Streaming (No Timeout)
```typescript
// Connect directly to backend with JWT
const es = new EventSource(`${backendUrl}/api/ai/search/results/${job_id}?token=${token}`);
```

## 🔧 Backend Changes

The backend now validates JWT tokens on streaming endpoints:

```python
@router.get("/search/results/{job_id}")
async def get_search_results(
    job_id: str,
    token_data: dict = Depends(validate_stream_token_async)
):
    # Verify token is for this specific job
    if token_data.get("jobId") != job_id:
        raise HTTPException(status_code=403, detail="Token not valid for this job")
    
    # Your existing streaming logic...
```

## 🌐 CORS Configuration

The backend CORS is configured to allow Vercel deployments:

```python
allow_origins=[
    "http://localhost:3000",          # Development
    "https://*.vercel.app",           # All Vercel deployments
    "https://your-domain.vercel.app"  # Your specific domain
]
```

## 🔐 Security Features

- **JWT tokens expire in 30 minutes** (configurable)
- **Tokens are job-specific** (can't be reused for other jobs)
- **User authentication required** (through NextAuth)
- **No sensitive data in frontend** (JWT_SECRET stays server-side)
- **CORS protection** (only allowed origins can connect)

## 🐛 Troubleshooting

### "JWT_SECRET not configured"
- Ensure `JWT_SECRET` is set in both frontend and backend `.env` files
- Values must be identical
- Restart both applications after setting

### "Token not valid for this job"
- This happens if someone tries to use a token for a different job ID
- Normal security measure, no action needed

### "Token expired" 
- Tokens expire after 30 minutes
- User needs to start a new search
- Consider increasing expiration time if needed

### CORS errors
- Update `allow_origins` in `ai-backend/app/main.py`
- Add your specific Vercel domain
- Ensure no trailing slashes in URLs

## 🔄 Migration from Previous Setup

If upgrading from the previous proxy-based setup:

1. ✅ **Frontend**: Install dependencies: `npm install jsonwebtoken @types/jsonwebtoken`
2. ✅ **Backend**: PyJWT is already included in your Poetry dependencies
3. ✅ Set up environment variables (see above)
4. ✅ Deploy backend with new auth code
5. ✅ Deploy frontend with updated streaming logic
6. ✅ Remove old Vercel proxy routes (optional cleanup)

## 📈 Benefits

- ✅ **No more 60-second timeouts**
- ✅ **Better security** (no exposed credentials)
- ✅ **Direct connection performance**
- ✅ **Unlimited streaming duration**
- ✅ **Proper authentication**

The system now supports searches that can run for minutes or hours without interruption! 