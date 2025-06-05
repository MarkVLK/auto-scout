# Contributing to Auto-Scout

Thank you for your interest in contributing to the Auto-Scout autonomous robot project! This document provides guidelines for contributing to the codebase.

## Development Setup

### Prerequisites
- Ubuntu 20.04 LTS (recommended for ROS Noetic)
- ROS Noetic installation
- Python 3.8+
- Git

### Setting Up Development Environment

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd auto-scout
   ```

2. **Install dependencies**:
   ```bash
   # Install ROS dependencies
   rosdep install --from-paths . --ignore-src -r -y
   
   # Install Python dependencies
   pip install -r requirements.txt
   ```

3. **Build the package**:
   ```bash
   cd ~/catkin_ws
   catkin_make
   source devel/setup.bash
   ```

## Code Style Guidelines

### Python Style
- Follow [PEP 8](https://pep8.org/) style guidelines
- Use descriptive variable and function names
- Add docstrings to all classes and functions
- Maximum line length: 100 characters
- Use type hints where appropriate

### ROS Conventions
- Follow [ROS naming conventions](http://wiki.ros.org/ROS/Patterns/Conventions)
- Use snake_case for node names and topic names
- Use CamelCase for service and action names
- Prefix custom messages/services with package name

### Example Code Style:
```python
#!/usr/bin/env python3
"""
Module description here.
"""

import rospy
from typing import Optional, Dict, List


class ExampleClass:
    """Class description."""
    
    def __init__(self, param: str):
        """Initialize the class."""
        self.param = param
        rospy.loginfo(f"Initialized with param: {param}")
    
    def process_data(self, data: Dict[str, Any]) -> Optional[List[str]]:
        """Process input data and return results."""
        # Implementation here
        pass
```

## Testing

### Running Tests
```bash
# Run all tests
python -m pytest tests/

# Run specific test file
python -m pytest tests/test_scout_system.py

# Run with coverage
python -m pytest --cov=src tests/
```

### Writing Tests
- Write unit tests for all new functions and classes
- Use descriptive test names that explain what is being tested
- Mock external dependencies (ROS topics, hardware interfaces)
- Test both success and failure cases

### Test Structure:
```python
import pytest
from unittest.mock import Mock, patch
from src.your_module import YourClass


class TestYourClass:
    """Test suite for YourClass."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.instance = YourClass()
    
    def test_method_success(self):
        """Test successful operation."""
        result = self.instance.method(valid_input)
        assert result == expected_output
    
    def test_method_invalid_input(self):
        """Test handling of invalid input."""
        with pytest.raises(ValueError):
            self.instance.method(invalid_input)
```

## Contribution Process

### 1. Issue Creation
- Check existing issues before creating new ones
- Use issue templates when available
- Provide clear description of the problem or feature request
- Include relevant system information and error messages

### 2. Branch Strategy
- Create feature branches from `main`
- Use descriptive branch names: `feature/dog-detection`, `bugfix/navigation-crash`
- Keep branches focused on single features or fixes

### 3. Pull Request Process
1. **Before submitting**:
   - Ensure all tests pass
   - Update documentation if needed
   - Add changelog entry for significant changes
   - Rebase on latest main branch

2. **Pull Request Requirements**:
   - Clear title and description
   - Reference related issues
   - Include test coverage for new code
   - Update relevant documentation

3. **Review Process**:
   - All PRs require at least one review
   - Address review feedback promptly
   - Maintain clean commit history

### 4. Commit Guidelines
- Use conventional commit format:
  ```
  type(scope): description
  
  feat(navigation): add dog search functionality
  fix(camera): resolve image capture timeout
  docs(readme): update installation instructions
  test(detection): add unit tests for dog detection
  ```

## Architecture Guidelines

### Module Organization
- Keep modules focused on single responsibilities
- Use dependency injection for hardware interfaces
- Implement proper error handling and logging
- Design for testability (avoid tight coupling)

### ROS Best Practices
- Use parameter server for configuration
- Implement proper node lifecycle management
- Handle node shutdown gracefully
- Use appropriate message types for communication

### Safety Considerations
- Always implement emergency stop functionality
- Validate sensor inputs before acting
- Implement timeouts for all operations
- Log safety-critical events

## Hardware Testing

### Simulation Testing
- Test in ROS simulation environment first
- Use mock hardware interfaces for unit testing
- Validate navigation algorithms in Gazebo

### Real Hardware Testing
- Test incrementally (sensors → navigation → full system)
- Always have manual override capability
- Test in controlled environment first
- Document hardware-specific configurations

## Documentation

### Code Documentation
- Add docstrings to all public methods
- Include parameter descriptions and return types
- Document any hardware dependencies
- Explain complex algorithms or state machines

### User Documentation
- Update README for new features
- Add configuration examples
- Include troubleshooting information
- Provide installation and setup instructions

## Getting Help

- **Questions**: Create a discussion or issue
- **Bugs**: Use the bug report template
- **Features**: Use the feature request template
- **Chat**: Join our development chat (if available)

## Recognition

Contributors will be recognized in:
- CHANGELOG.md for significant contributions
- README.md contributors section
- Release notes for major features

Thank you for helping make Auto-Scout better!
