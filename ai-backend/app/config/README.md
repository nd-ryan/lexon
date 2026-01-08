# External API Configuration

This directory contains centralized configuration for the External API.

## Configuration Module

`external_api.py` contains all external API constants:
- Query limits (min/max length, result limits)
- Rate limiting configuration
- Timeout values

## Updating Configuration

To update any external API limits or settings:

1. **Edit `external_api.py`** - Update the constant values
2. **Run the documentation generator**:
   ```bash
   cd ai-backend
   python scripts/generate_external_api_docs.py --format all
   ```
3. **Update documentation files** using the generated values:
   - `docs/EXTERNAL_API.md`
   - `docs/CLIENT_QUICKSTART.md`
   - `src/app/docs/api/quickstart/page.tsx`
   - `public/lexon-external-api.postman_collection.json`

## Code Usage

All code automatically uses the config values:

```python
from app.config.external_api import QUERY_MAX_LENGTH, RATE_LIMIT

# Use in Pydantic models
max_length=QUERY_MAX_LENGTH

# Use in rate limiting
@limiter.limit(RATE_LIMIT)
```

## Documentation Generation

The `generate_external_api_docs.py` script outputs values in multiple formats:

- `--format markdown` - Markdown table format
- `--format json` - JSON format
- `--format table` - Single table row for request body tables
- `--format field` - Field description format
- `--format all` - All formats (default)

## Benefits

✅ Single source of truth for all API limits
✅ Automatic consistency across code, tests, and docs
✅ Easy to update - change once, regenerate docs
✅ Type-safe constants in Python code
