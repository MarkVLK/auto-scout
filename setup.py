#!/usr/bin/env python3
"""
Setup script for the auto-scout package.
"""

from setuptools import setup, find_packages
import os

def read_requirements():
    """Read requirements from requirements.txt"""
    requirements_path = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    if os.path.exists(requirements_path):
        with open(requirements_path, 'r') as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    return []

def read_long_description():
    """Read long description from README.md"""
    readme_path = os.path.join(os.path.dirname(__file__), 'README.md')
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            return f.read()
    return "Auto-Scout: Autonomous pet search and rescue robot"

setup(
    name="auto-scout",
    version="1.0.0",
    author="Auto-Scout Development Team",
    author_email="dev@auto-scout.com",
    description="Autonomous pet search and rescue robot based on Moorebot Scout",
    long_description=read_long_description(),
    long_description_content_type="text/markdown",
    url="https://github.com/your-org/auto-scout",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering :: Robotics",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Hardware",
        "Topic :: System :: Embedded Systems",
    ],
    python_requires=">=3.5",
    install_requires=read_requirements(),
    extras_require={
        "dev": [
            "pytest>=4.6.0,<6.0.0",      # Python 3.5 compatible
            "pytest-cov>=2.8.0,<3.0.0",  # Python 3.5 compatible
            "black>=19.0,<22.0",          # Python 3.5 compatible
            "flake8>=3.7.0,<4.0.0",      # Python 3.5 compatible
            "mypy>=0.720,<0.900",         # Python 3.5 compatible
        ],
        "ros": [
            # ROS dependencies are handled by rosdep
            # Listed here for documentation purposes
        ],
    },
    entry_points={
        "console_scripts": [
            "scout-navigation=scout_navigation_controller:main",
            "scout-web=scout_web_interface:main",
            "scout-camera=scout_camera_driver:main",
            "scout-lidar=ld19_lidar_driver:main",
            "scout-voice=voice_command_interface:main",
            "scout-detection=dog_detection_module:main",
        ],
    },
    include_package_data=True,
    package_data={
        "": ["*.yaml", "*.json", "*.xml", "*.launch", "*.rviz"],
    },
    zip_safe=False,
)
