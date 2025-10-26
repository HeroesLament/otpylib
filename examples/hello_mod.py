"""
hello_mod.py

Introduction to plain OTPModules - modules without behaviors.

This demonstrates that otpylib modules don't always need to be processes.
Plain modules are just collections of functions that benefit from:
- Version tracking
- Hot code reloading (when code_server is implemented)
- Module registry and introspection
- Dependency management
"""

from otpylib.module import OTPModule
from otpylib.module.core import get_module_info, is_otp_module


# ============================================================================
# Plain Module Example - No Behavior Required
# ============================================================================

class MathUtils(metaclass=OTPModule, version="1.0.0"):
    """
    A plain module - just functions, no process behavior.
    
    Notice: No behavior= parameter! This is a plain module.
    It can be instantiated like any Python class.
    """
    
    def add(self, a, b):
        """Add two numbers."""
        return a + b
    
    def multiply(self, a, b):
        """Multiply two numbers."""
        return a * b
    
    def factorial(self, n):
        """Calculate factorial."""
        if n <= 1:
            return 1
        return n * self.factorial(n - 1)


class StringUtils(metaclass=OTPModule, version="1.0.0"):
    """Another plain module with string utilities."""
    
    def reverse(self, s):
        """Reverse a string."""
        return s[::-1]
    
    def capitalize_words(self, s):
        """Capitalize each word."""
        return ' '.join(word.capitalize() for word in s.split())


# ============================================================================
# Test and Demonstrate
# ============================================================================

def main():
    print("=" * 70)
    print("Plain OTPModule Example")
    print("=" * 70)
    print()
    
    # Verify these are OTP modules
    print("✓ MathUtils is an OTPModule:", is_otp_module(MathUtils))
    print("✓ StringUtils is an OTPModule:", is_otp_module(StringUtils))
    print()
    
    # Check that they DON'T have start_link (not process modules)
    print("✓ MathUtils has start_link:", hasattr(MathUtils, 'start_link'))
    print("  (Should be False - plain modules don't spawn processes)")
    print()
    
    # Instantiate and use like normal Python classes
    print("Creating instances...")
    math = MathUtils()
    strings = StringUtils()
    print()
    
    # Use them
    print("Using MathUtils:")
    print(f"  math.add(2, 3) = {math.add(2, 3)}")
    print(f"  math.multiply(4, 5) = {math.multiply(4, 5)}")
    print(f"  math.factorial(5) = {math.factorial(5)}")
    print()
    
    print("Using StringUtils:")
    print(f"  strings.reverse('hello') = {strings.reverse('hello')}")
    print(f"  strings.capitalize_words('hello world') = {strings.capitalize_words('hello world')}")
    print()
    
    # Show metadata
    print("Module Metadata:")
    print("-" * 70)
    math_info = get_module_info(MathUtils)
    print(f"MathUtils:")
    print(f"  mod_id: {math_info['mod_id']}")
    print(f"  version: {math_info['version']}")
    print(f"  behavior: {math_info['behavior']}")
    print(f"  callbacks: {math_info['callbacks']}")
    print()
    
    string_info = get_module_info(StringUtils)
    print(f"StringUtils:")
    print(f"  mod_id: {string_info['mod_id']}")
    print(f"  version: {string_info['version']}")
    print(f"  behavior: {string_info['behavior']}")
    print(f"  callbacks: {string_info['callbacks']}")
    print()
    
    # Show instance tracking (for future hot-reload)
    print("Instance Tracking (for hot-reload):")
    print(f"  MathUtils.__instances__: {len(MathUtils.__instances__)} instance(s)")
    print(f"  StringUtils.__instances__: {len(StringUtils.__instances__)} instance(s)")
    print()
    
    print("=" * 70)
    print("Key Takeaways:")
    print("=" * 70)
    print("1. Plain modules don't need behavior= parameter")
    print("2. They can be instantiated like normal Python classes")
    print("3. They still get version tracking and metadata")
    print("4. They're tracked for future hot-reload support")
    print("5. They DON'T have start_link() - they're not processes")
    print()
    print("Use plain modules for:")
    print("  - Utility functions")
    print("  - Codecs and parsers")
    print("  - HTTP handlers (coming soon!)")
    print("  - Any code that doesn't need to run as a process")


if __name__ == '__main__':
    main()
