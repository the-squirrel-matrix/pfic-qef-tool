"""
Setup script for PFIC QEF Tax Tool.

For development installation:
    pip install -e .

For normal installation:
    pip install .
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README for long description
readme_path = Path(__file__).parent / "README.md"
long_description = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

setup(
    name="pfic-qef-tool",
    version="1.0.0",
    author="the_squirrel_matrix",
    description="Calculate QEF income and basis adjustments for PFIC holdings",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/YOUR_USERNAME/pfic_qef_tool",  # Update when creating repo
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        # Core package has no required dependencies
    ],
    extras_require={
        "excel": ["openpyxl>=3.0.0"],
        "pdf": ["reportlab>=3.6.0"],
        "full": ["openpyxl>=3.0.0", "reportlab>=3.6.0"],
    },
    entry_points={
        "console_scripts": [
            "pfic-qef-tool=pfic_qef_tool.main:main",
            "pfic-qef-gui=pfic_qef_tool.gui:main",
        ],
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: End Users/Desktop",
        "Topic :: Office/Business :: Financial :: Accounting",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    keywords="pfic qef tax irs form-8621 canadian-etf",
    project_urls={
        "Source": "https://github.com/YOUR_USERNAME/pfic_qef_tool",  # Update when creating repo
        "Bug Reports": "https://github.com/YOUR_USERNAME/pfic_qef_tool/issues",  # Update when creating repo
    },
)
