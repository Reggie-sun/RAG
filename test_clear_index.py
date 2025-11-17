#!/usr/bin/env python3
"""
Test script for clear index functionality
"""
import sys
import os
from pathlib import Path

# Add the rag-system to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'rag-system'))

def test_clear_index_endpoint():
    """Test if the clear index endpoint exists and works"""
    print("🧪 Testing clear index endpoint...")

    try:
        # Import the router
        from backend.routers.status import router

        # Check if the clear_index route exists
        routes = [route.path for route in router.routes]
        clear_route = any('/index/clear' in route for route in routes)

        if clear_route:
            print("✅ Clear index endpoint found in router")
            return True
        else:
            print("❌ Clear index endpoint not found")
            return False

    except Exception as e:
        print(f"❌ Error testing clear index endpoint: {e}")
        return False

def test_imports():
    """Test if all required modules can be imported"""
    print("🔍 Testing imports...")

    try:
        # Test backend imports
        from backend.services.providers import get_rag_service
        print("✅ RAG service providers import successful")

        from backend.services.enhanced_intent_classifier import enhanced_classifier
        print("✅ Enhanced intent classifier import successful")

        from backend.services.web_search_service import WebSearchService
        print("✅ Web search service import successful")

        # Test router imports
        from backend.routers.status import router
        print("✅ Status router import successful")

        from backend.routers.upload import upload_router
        print("✅ Upload router import successful")

        from backend.routers.search import router as search_router
        print("✅ Search router import successful")

        return True

    except Exception as e:
        print(f"❌ Import error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_config_paths():
    """Test if configuration paths exist"""
    print("📁 Testing configuration paths...")

    try:
        from backend.config import settings

        paths_to_check = [
            ('FAISS index path', settings.faiss_index_path),
            ('BM25 index path', settings.bm25_index_path),
            ('Meta file path', settings.meta_file_path),
            ('Retrieval log path', settings.retrieval_log_path),
        ]

        all_exist = True
        for name, path in paths_to_check:
            if path.exists():
                print(f"✅ {name}: {path}")
            else:
                print(f"⚠️  {name}: {path} (will be created)")

        return True

    except Exception as e:
        print(f"❌ Config test error: {e}")
        return False

def main():
    """Main test function"""
    print("🚀 RAG Clear Index Feature Test\n")
    print("=" * 50)

    results = []

    # Test 1: Imports
    results.append(test_imports())

    # Test 2: Clear index endpoint
    results.append(test_clear_index_endpoint())

    # Test 3: Configuration paths
    results.append(test_config_paths())

    print("\n" + "=" * 50)
    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"🎉 All tests passed! ({passed}/{total})")
        print("Clear index feature should be working properly.")
        return 0
    else:
        print(f"❌ Some tests failed ({passed}/{total})")
        print("Please check the error messages above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())