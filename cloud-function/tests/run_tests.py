#!/usr/bin/env python3
"""
Test Runner for Event Blocking System

Runs all unit tests for the event blocking features.
"""

import unittest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def run_all_tests():
    """Run all test suites"""
    
    # Discover and run all tests
    loader = unittest.TestLoader()
    start_dir = Path(__file__).parent
    suite = loader.discover(start_dir, pattern='test_*.py')
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    
    if result.wasSuccessful():
        print("\n✅ ALL TESTS PASSED!")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED")
        return 1


def run_specific_test(test_file):
    """Run a specific test file"""
    
    loader = unittest.TestLoader()
    suite = loader.discover(Path(__file__).parent, pattern=test_file)
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return 0 if result.wasSuccessful() else 1


def list_available_tests():
    """List all available test files"""
    
    test_dir = Path(__file__).parent
    test_files = sorted(test_dir.glob('test_*.py'))
    
    print("\nAvailable test files:")
    print("="*70)
    for test_file in test_files:
        print(f"  - {test_file.name}")
    print()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == 'list':
            list_available_tests()
            sys.exit(0)
        else:
            # Run specific test file
            test_file = sys.argv[1]
            if not test_file.startswith('test_'):
                test_file = f'test_{test_file}'
            if not test_file.endswith('.py'):
                test_file = f'{test_file}.py'
            
            print(f"Running tests from: {test_file}")
            sys.exit(run_specific_test(test_file))
    else:
        # Run all tests
        sys.exit(run_all_tests())
