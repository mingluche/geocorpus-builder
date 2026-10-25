"""GeoCorpusProject -- manage project directory lifecycle."""

import json
import shutil
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Optional

from .settings import GeoCorpusSettings


_BUNDLED_FILES = [
    "geocorpus_schema.json",
    "corpus_units_seed.jsonl",
    "qa_pairs_seed.jsonl",
    "geo_concepts.json",
    "variable_dictionary.json",
    "relation_dictionary.json",
    "evidence_links_template.csv",
    "layer_registry_template.csv",
    "geocorpus_agent_system_prompt.md",
]


@dataclass
class GeoCorpusProject:
    """Represents a GeoCorpus project directory on disk."""

    root: Path
    config: GeoCorpusSettings = field(default_factory=GeoCorpusSettings)

    @classmethod
    def init(cls, path: Path, domain: str = "cryosphere",
             subdomain: str = "glacier") -> "GeoCorpusProject":
        """Initialize a new GeoCorpus project directory."""
        root = path.resolve()
        root.mkdir(parents=True, exist_ok=True)
        settings = GeoCorpusSettings(domain=domain, subdomain=subdomain)

        # Create directory structure
        (root / settings.data_dir).mkdir(exist_ok=True)
        (root / settings.corpus_dir).mkdir(exist_ok=True)
        (root / settings.evidence_dir).mkdir(exist_ok=True)
        (root / settings.templates_dir).mkdir(exist_ok=True)
        (root / "statistics").mkdir(exist_ok=True)

        # Write config file
        cls._write_config(root, settings)

        project = cls(root=root, config=settings)

        # Copy bundled seed data
        for filename in _BUNDLED_FILES:
            project._copy_bundled(filename, root / settings.data_dir / filename)

        return project

    @classmethod
    def discover(cls, path: Path) -> Optional["GeoCorpusProject"]:
        """Discover a GeoCorpus project at the given path (look for config file)."""
        root = path.resolve()
        config_paths = [
            root / "geocorpus_config.json",
            root / "config.json",
        ]
        for cp in config_paths:
            if cp.exists():
                config = GeoCorpusSettings.model_validate_json(cp.read_text(encoding="utf-8"))
                return cls(root=root, config=config)

        # No config found, return a default project
        return cls(root=root)

    def locate_file(self, relative_path: str) -> Optional[Path]:
        """Find a file by relative path within the project."""
        full = self.root / relative_path
        if full.exists():
            return full
        return None

    def corpus_units_path(self) -> Path:
        return self.root / self.config.corpus_dir / "corpus_units.jsonl"

    def evidence_links_path(self) -> Path:
        return self.root / self.config.evidence_dir / "evidence_links.jsonl"

    def qa_pairs_path(self) -> Path:
        return self.root / self.config.corpus_dir / "qa_pairs.jsonl"

    @staticmethod
    def _write_config(root: Path, settings: GeoCorpusSettings) -> None:
        config_path = root / "geocorpus_config.json"
        config_path.write_text(
            settings.model_dump_json(indent=2), encoding="utf-8"
        )

    @staticmethod
    def _copy_bundled(filename: str, dest: Path) -> None:
        """Copy a bundled data file to the project directory."""
        try:
            data_ref = resources.files("geocorpus_builder.data").joinpath(filename)
            if data_ref.is_file():
                shutil.copy(str(data_ref), str(dest))
        except Exception:
            pass
