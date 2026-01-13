import os
import json
import threading
import logging
from typing import Dict, Any
from config import Config

logger = logging.getLogger(__name__)
projects_lock = threading.Lock()

def load_projects() -> Dict[str, Any]:
    """Load projects from disk."""
    try:
        if not os.path.exists(Config.PROJECT_DATA_FILE):
            return {}
        with open(Config.PROJECT_DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load projects: {str(e)}")
        return {}

def save_projects(data: Dict[str, Any]) -> None:
    """Persist projects to disk."""
    try:
        with open(Config.PROJECT_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save projects: {str(e)}")

def get_projects() -> Dict[str, Any]:
    with projects_lock:
        return load_projects()

def update_projects(mutator):
    """Thread-safe project mutation helper."""
    with projects_lock:
        data = load_projects()
        mutated = mutator(data) or data
        save_projects(mutated)
        return mutated
