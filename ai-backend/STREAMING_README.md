# Streaming Search Implementation

This document describes the Server-Sent Events (SSE) streaming implementation for the AI-powered search functionality.

## Overview

The streaming search provides real-time updates during the AI processing, solving the timeout issues that occur with long-running CrewAI operations (which can take 2-3 minutes).

## Architecture

### Backend (FastAPI)
- **Endpoint**: `POST /api/ai/search/crew/stream`
- **Response Type**: Server-Sent Events (SSE)
- **Media Type**: `text/plain`

### Frontend (Next.js)
- **Proxy Endpoint**: `POST /api/search/crew/stream`
- **Client**: Uses Fetch API with ReadableStream reader
- **UI**: Real-time progress display with status updates

## Event Types

The streaming endpoint sends different types of events:

### 1. Status Events
```json
{
  "type": "status",
  "message": "Initializing AI search...",
  "timestamp": 1234567890.123
}
```

### 2. Progress Events
```json
{
  "type": "progress", 
  "message": "Executing Cypher queries against Neo4j...",
  "timestamp": 1234567890.123
}
```

### 3. Warning Events
```json
{
  "type": "warning",
  "message": "No MCP tools available, using basic agent",
  "timestamp": 1234567890.123
}
```

### 4. Complete Events
```json
{
  "type": "complete",
  "data": {
    "success": true,
    "query": "user query",
    "total_results": 5,
    "results": [...],
    "analysis": {...},
    "execution_time": 45.67
  },
  "timestamp": 1234567890.123
}
```

### 5. Error Events
```json
{
  "type": "error",
  "message": "Error description",
  "timestamp": 1234567890.123
}
```

## Implementation Details

### Backend Streaming Generator

The backend uses an async generator function that:
1. Initializes MCP tools and agents
2. Sends status updates at each major step
3. Executes the CrewAI search
4. Processes results and sends completion event
5. Handles errors gracefully

### Frontend Event Processing

The frontend:
1. Makes a POST request to the streaming endpoint
2. Gets a ReadableStream reader
3. Processes incoming chunks line by line
4. Parses SSE data format (`data: {...}`)
5. Updates UI based on event types
6. Handles completion and error states

### UI Components

- **Loading State**: Shows during streaming with animated spinner
- **Status Display**: Current operation being performed
- **Progress Log**: Scrollable list of all status updates
- **Error Display**: User-friendly error messages
- **Result Display**: Final search results when complete

## Benefits

1. **No Timeouts**: Bypasses Vercel's 60-second timeout limit
2. **Real-time Feedback**: Users see progress instead of waiting blindly
3. **Better UX**: Transparent process with status updates
4. **Error Handling**: Immediate feedback on failures
5. **Scalable**: Can handle operations of any duration

## Testing

Use the included test script:

```bash
cd ai-backend
python test_streaming.py
```

This will test the streaming endpoint locally and display all events.

## Deployment Considerations

- **Vercel**: Streaming responses work with Vercel's edge runtime
- **Fly.io**: FastAPI streaming is fully supported
- **CORS**: Proper headers are set for cross-origin streaming
- **Error Handling**: Graceful degradation if streaming fails

## Future Enhancements

1. **Progress Percentage**: Add completion percentage to progress events
2. **Cancellation**: Allow users to cancel long-running operations
3. **Retry Logic**: Automatic retry on connection failures
4. **Metrics**: Track streaming performance and success rates
5. **WebSocket Upgrade**: Consider WebSocket for bidirectional communication 