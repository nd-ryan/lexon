import logging
import sys
import warnings
import os


def configure_root_logging():
    """
    Configure the root logger to prevent duplicate messages and noise.
    Call this FIRST before any other logging setup.
    """
    # Get the root logger
    root_logger = logging.getLogger()
    
    # Clear all existing handlers from root logger
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Set root logger to CRITICAL to suppress most noise
    root_logger.setLevel(logging.CRITICAL)
    
    # Disable basicConfig to prevent auto-configuration
    logging.basicConfig(handlers=[], level=logging.CRITICAL)


def setup_logger(name: str = "crew") -> logging.Logger:
    """
    Set up a properly configured logger with real-time output and optional file logging.
    
    Args:
        name: Logger name (defaults to "crew")
        
    Returns:
        Configured logger instance
    """
    import os  # Import at top of function
    
    logger = logging.getLogger(name)
    
    # Clear any existing handlers to prevent duplicates
    logger.handlers.clear()
    
    # Don't propagate to avoid noise
    logger.propagate = False
    logger.setLevel(logging.DEBUG)

    # Create console handler with real-time output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    # Detect if we're running under a process manager (honcho/foreman)
    # These add their own timestamps, so we should omit ours to avoid duplication
    is_under_process_manager = (
        os.environ.get("FOREMAN") or          # Honcho/Foreman sets this
        os.environ.get("HONCHO") or           # Some versions use this
        os.environ.get("PROC_TYPE") or        # Process type in Procfile
        "honcho" in str(sys.argv) or          # Running via honcho
        "foreman" in str(sys.argv) or         # Running via foreman
        # Check parent process name patterns common with process managers
        any(proc_name in os.environ.get("_", "").lower() 
            for proc_name in ["honcho", "foreman", "procfile"])
    )
    
    if is_under_process_manager:
        # No timestamp since process manager adds one
        console_formatter = logging.Formatter(fmt="[%(levelname)s] %(message)s")
    else:
        # Include timestamp when running standalone
        console_formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S"
        )
    
    console_handler.setFormatter(console_formatter)
    
    # Force line buffering for real-time output
    sys.stdout.reconfigure(line_buffering=True)
    
    logger.addHandler(console_handler)
    
    # Add file handler for clean file logging (no third-party noise)
    # Resolve logs directory relative to the ai-backend project root to avoid CWD issues
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    log_dir = os.path.join(base_dir, "logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    file_handler = logging.FileHandler(os.path.join(log_dir, "app.log"))
    file_handler.setLevel(logging.DEBUG)
    
    # Clean file formatter with full timestamp
    file_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    return logger


def setup_clean_file_logging():
    """
    Set up clean file logging - only our app logs, no third-party noise.
    This gives clean logs in both console AND file.
    """
    import os
    
    # Set environment variables to suppress CrewAI's verbose output
    os.environ.setdefault("CREWAI_VERBOSE", "false")
    os.environ.setdefault("CREWAI_LOGS", "false")
    
    # Create logs directory relative to the ai-backend project root
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    log_dir = os.path.join(base_dir, "logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Aggressively suppress all noisy third-party loggers
    noisy_loggers = [
        "pydantic", "pydantic.fields", "pydantic.main", "pydantic._internal",
        "chromadb", "httpx", "urllib3", "asyncio", "httpcore", 
        "crewai", "crewai.flow", "crewai.agent", "crewai.crew", "crewai.task",
        "mcp", "mcp.server", "server", "rich", "rich.console",
        "litellm", "litellm.proxy", "litellm.utils", "openai._base_client"
    ]
    
    for logger_name in noisy_loggers:
        noisy_logger = logging.getLogger(logger_name)
        noisy_logger.setLevel(logging.CRITICAL)
        noisy_logger.propagate = False  # Don't propagate noise


def setup_file_logging(logger: logging.Logger, filename: str = "crew_flow.log"):
    """
    Add file logging to an existing logger for debugging long-running flows.
    
    Args:
        logger: Logger instance to add file handler to
        filename: Log file name (defaults to "crew_flow.log")
    """
    # Ensure file path is under the ai-backend logs directory if a bare filename is provided
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    logs_dir = os.path.join(base_dir, "logs")
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    file_path = filename if os.path.isabs(filename) else os.path.join(logs_dir, filename)
    file_handler = logging.FileHandler(file_path)
    file_handler.setLevel(logging.DEBUG)
    
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler) 