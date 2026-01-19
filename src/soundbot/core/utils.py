"""Utility functions for parsing and formatting."""

import re
from typing import Optional


def parse_timestamp(value: str) -> Optional[float]:
    """Parse a timestamp string into seconds.
    
    Supports multiple formats:
    - Plain seconds: "90", "90.5"
    - MM:SS format: "1:30" (1 minute 30 seconds = 90 seconds)
    - HH:MM:SS format: "1:30:00" (1 hour 30 minutes = 5400 seconds)
    
    Returns None if the value cannot be parsed.
    """
    if not value:
        return None
    
    value = value.strip()
    
    # Try plain number first (seconds)
    try:
        return float(value)
    except ValueError:
        pass
    
    # Try MM:SS or HH:MM:SS format
    # Match patterns like "1:30", "01:30", "1:30:00", "1:30.5"
    match = re.match(r'^(\d+):(\d{1,2})(?::(\d{1,2}))?(?:\.(\d+))?$', value)
    if match:
        parts = match.groups()
        
        if parts[2] is not None:
            # HH:MM:SS format
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
            fraction = float(f"0.{parts[3]}") if parts[3] else 0.0
            return hours * 3600 + minutes * 60 + seconds + fraction
        else:
            # MM:SS format
            minutes = int(parts[0])
            seconds = int(parts[1])
            fraction = float(f"0.{parts[3]}") if parts[3] else 0.0
            return minutes * 60 + seconds + fraction
    
    return None


def format_timestamp(seconds: Optional[float]) -> str:
    """Format seconds as a human-readable timestamp.
    
    Returns MM:SS or HH:MM:SS format depending on duration.
    """
    if seconds is None:
        return "N/A"
    
    seconds = float(seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:05.2f}"
    else:
        return f"{minutes}:{secs:05.2f}"
