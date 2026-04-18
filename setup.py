"""Setup configuration for the multi-team agentic coding harness."""

from setuptools import setup, find_packages

setup(
    name="harness",
    version="0.1.0",
    description="Multi-team agentic coding harness — orchestrates Claude Code agents in a three-tier architecture",
    author="Harness Team",
    python_requires=">=3.11",
    packages=find_packages(),
    install_requires=[
        "pyyaml>=6.0",
        "rich>=13.0",
        "aiofiles>=23.0",
    ],
    entry_points={
        "console_scripts": [
            "harness=harness.cli:main",
        ],
    },
)
