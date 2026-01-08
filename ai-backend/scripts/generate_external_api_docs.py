#!/usr/bin/env python3
"""
Generate documentation values from external API configuration.

This script extracts configuration values from app.config.external_api
and outputs them in various formats for use in documentation files.

Usage:
    python scripts/generate_external_api_docs.py --format markdown
    python scripts/generate_external_api_docs.py --format json
    python scripts/generate_external_api_docs.py --format table
"""
import sys
import json
from pathlib import Path

# Add parent directory to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config.external_api import (
    QUERY_MAX_LENGTH,
    QUERY_MIN_LENGTH,
    QUERY_RESULT_LIMIT_MAX,
    QUERY_RESULT_LIMIT_DEFAULT,
    RATE_LIMIT_NUMERIC,
    RATE_LIMIT_PERIOD,
    QUERY_TIMEOUT_SECONDS,
    format_query_length_description,
    format_rate_limit_description,
    get_config_dict,
)


def format_markdown_table():
    """Generate markdown table format."""
    return f"""| Limit | Value |
|-------|-------|
| Max query length | {QUERY_MAX_LENGTH:,} characters |
| Request timeout | {QUERY_TIMEOUT_SECONDS:.0f} seconds |
| Rate limit | {format_rate_limit_description()} per API key |"""


def format_field_description():
    """Generate field description format."""
    return format_query_length_description()


def format_json():
    """Generate JSON format."""
    config = get_config_dict()
    return json.dumps(config, indent=2)


def format_table_row():
    """Generate single table row format."""
    return f"| `query` | string | Yes | - | {format_query_length_description()} |"


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate external API documentation values"
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json", "table", "field", "all"],
        default="all",
        help="Output format (default: all)"
    )
    
    args = parser.parse_args()
    
    if args.format == "all":
        print("=" * 60)
        print("External API Configuration Values")
        print("=" * 60)
        print()
        
        print("Markdown Table:")
        print("-" * 60)
        print(format_markdown_table())
        print()
        
        print("Field Description:")
        print("-" * 60)
        print(format_field_description())
        print()
        
        print("Table Row (for request body tables):")
        print("-" * 60)
        print(format_table_row())
        print()
        
        print("JSON:")
        print("-" * 60)
        print(format_json())
        print()
        
        print("=" * 60)
        print("Individual Values:")
        print("=" * 60)
        config = get_config_dict()
        for key, value in config.items():
            print(f"  {key}: {value}")
    
    elif args.format == "markdown":
        print(format_markdown_table())
    elif args.format == "json":
        print(format_json())
    elif args.format == "table":
        print(format_table_row())
    elif args.format == "field":
        print(format_field_description())


if __name__ == "__main__":
    main()
