"""
Project Manager
Manages project structure and organization.
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime


class ProjectManager:
    """Manages haptic software projects."""
    
    def __init__(self, project_base_dir: str = "./projects"):
        """
        Initialize project manager.
        
        Args:
            project_base_dir: Base directory for projects
        """
        self.project_base_dir = Path(project_base_dir)
        self.current_project = None
        self.project_metadata_file = "project.json"
    
    def create_project(
        self,
        project_name: str,
        author: str = "User",
        description: str = "",
    ) -> Path:
        """
        Create new project directory structure.
        
        Args:
            project_name: Name of project
            author: Project author
            description: Project description
        
        Returns:
            Path to project directory
        """
        project_dir = self.project_base_dir / project_name
        
        # Create subdirectories
        subdirs = [
            "recordings",
            "models",
            "characterizations",
            "compensation",
            "evaluation",
            "exports",
            "temp",
        ]
        
        for subdir in subdirs:
            (project_dir / subdir).mkdir(parents=True, exist_ok=True)
        
        # Create metadata file
        metadata = {
            "name": project_name,
            "author": author,
            "description": description,
            "created": datetime.now().isoformat(),
            "modified": datetime.now().isoformat(),
            "version": "1.0",
        }
        
        with open(project_dir / self.project_metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        self.current_project = project_dir
        return project_dir
    
    def open_project(self, project_path: str) -> bool:
        """
        Open existing project.
        
        Args:
            project_path: Path to project directory
        
        Returns:
            True if successful
        """
        project_dir = Path(project_path)
        
        if not project_dir.exists():
            raise FileNotFoundError(f"Project not found: {project_path}")
        
        metadata_file = project_dir / self.project_metadata_file
        if not metadata_file.exists():
            raise FileNotFoundError(f"Not a valid project: {project_path}")
        
        self.current_project = project_dir
        return True
    
    def get_project_path(self, subdirectory: str = None) -> Path:
        """
        Get path to project subdirectory.
        
        Args:
            subdirectory: Subdirectory name (None = root)
        
        Returns:
            Path to directory
        """
        if self.current_project is None:
            raise RuntimeError("No project open")
        
        if subdirectory:
            path = self.current_project / subdirectory
        else:
            path = self.current_project
        
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def get_recordings_path(self) -> Path:
        """Get recordings directory."""
        return self.get_project_path("recordings")
    
    def get_models_path(self) -> Path:
        """Get models directory."""
        return self.get_project_path("models")
    
    def get_characterizations_path(self) -> Path:
        """Get characterizations directory."""
        return self.get_project_path("characterizations")
    
    def get_compensation_path(self) -> Path:
        """Get compensation directory."""
        return self.get_project_path("compensation")
    
    def get_evaluation_path(self) -> Path:
        """Get evaluation directory."""
        return self.get_project_path("evaluation")
    
    def get_exports_path(self) -> Path:
        """Get exports directory."""
        return self.get_project_path("exports")
    
    def list_projects(self) -> List[str]:
        """
        List all projects.
        
        Returns:
            List of project names
        """
        if not self.project_base_dir.exists():
            return []
        
        projects = []
        for item in self.project_base_dir.iterdir():
            if item.is_dir() and (item / self.project_metadata_file).exists():
                projects.append(item.name)
        
        return sorted(projects)
    
    def get_project_metadata(self, project_name: Optional[str] = None) -> Dict:
        """
        Get project metadata.
        
        Args:
            project_name: Project name (None = current project)
        
        Returns:
            Metadata dictionary
        """
        if project_name is None:
            if self.current_project is None:
                raise RuntimeError("No project open")
            project_dir = self.current_project
        else:
            project_dir = self.project_base_dir / project_name
        
        metadata_file = project_dir / self.project_metadata_file
        
        with open(metadata_file, 'r') as f:
            return json.load(f)
    
    def save_session_state(self, state: Dict) -> None:
        """
        Save session state to project.
        
        Args:
            state: Session state dictionary
        """
        if self.current_project is None:
            raise RuntimeError("No project open")
        
        state_file = self.current_project / "session.json"
        
        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2, default=str)
    
    def load_session_state(self) -> Dict:
        """
        Load session state from project.
        
        Returns:
            Session state dictionary
        """
        if self.current_project is None:
            raise RuntimeError("No project open")
        
        state_file = self.current_project / "session.json"
        
        if not state_file.exists():
            return {}
        
        with open(state_file, 'r') as f:
            return json.load(f)
    
    def delete_project(self, project_name: str) -> None:
        """Delete a project."""
        import shutil
        
        project_dir = self.project_base_dir / project_name
        
        if project_dir.exists():
            shutil.rmtree(project_dir)
            
            if self.current_project == project_dir:
                self.current_project = None
