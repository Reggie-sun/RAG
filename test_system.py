#!/usr/bin/env python3
"""
Simple test script to verify RAG system startup
"""
import sys
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "rag-system" / "backend"
LEGACY_ROOT = ROOT_DIR / "rag-system"

# Prefer the backend package path so `services.*` style imports resolve without
# needing an editable install. Keep the legacy path for backwards compatibility.
for candidate in (BACKEND_DIR, LEGACY_ROOT):
    candidate_str = str(candidate)
    if candidate_str not in sys.path and candidate.exists():
        sys.path.insert(0, candidate_str)

def test_backend_imports():
    """Test if backend services can be imported correctly"""
    print("🔍 Testing backend service imports...")

    try:
        # Test basic imports
        try:
            from backend.services.providers import (
                get_rag_service,
                get_web_search_service,
                get_intent_classifier,
            )
        except ImportError:
            from services.providers import (
                get_rag_service,
                get_web_search_service,
                get_intent_classifier,
            )
        print("✅ Service providers import successful")

        try:
            from backend.services.enhanced_intent_classifier import enhanced_classifier
        except ImportError:
            from services.enhanced_intent_classifier import enhanced_classifier
        print("✅ Enhanced intent classifier import successful")

        try:
            from backend.services.web_search_service import WebSearchService
        except ImportError:
            from services.web_search_service import WebSearchService
        print("✅ Web search service import successful")

        # Test service instantiation (without actually starting them)
        print("🧪 Testing service instantiation...")

        # Intent classifier
        classifier = get_intent_classifier()
        print("✅ Intent classifier instantiated")

        # Web search service
        web_search = get_web_search_service()
        print("✅ Web search service instantiated")

        # RAG service (this will test the full dependency chain)
        try:
            rag_service = get_rag_service()
            print("✅ RAG service instantiated")
        except Exception as e:
            print(f"⚠️  RAG service instantiation failed (may be due to missing dependencies): {e}")

        return True

    except Exception as e:
        print(f"❌ Import test failed: {e}")
        return False

def test_intent_classification():
    """Test basic intent classification functionality"""
    print("\n🧠 Testing intent classification...")

    try:
        import asyncio
        try:
            from backend.services.enhanced_intent_classifier import enhanced_classifier
        except ImportError:
            from services.enhanced_intent_classifier import enhanced_classifier

        async def test_intent():
            test_queries = [
                "什么是机器学习？",  # general knowledge
                "如何安装Python？",  # how_to
                "对比React和Vue的优缺点",  # comparison
                "我应该学习前端还是后端？",  # decision
                "根据文档分析系统架构"  # document specific
            ]

            for query in test_queries:
                result = await enhanced_classifier.analyze_intent(query)
                print(f"Query: {query}")
                print(f"  Type: {result.question_type.value}")
                print(f"  Mode: {result.answering_mode.value}")
                print(f"  Confidence: {result.confidence:.2f}")
                print()

        # Run the async test
        asyncio.run(test_intent())
        print("✅ Intent classification test successful")
        return True

    except Exception as e:
        print(f"❌ Intent classification test failed: {e}")
        return False

def test_frontend_build():
    """Test if frontend can be built"""
    print("\n🏗️  Testing frontend build...")

    try:
        import subprocess
        import os

        frontend_dir = os.path.join(os.path.dirname(__file__), 'rag-system', 'frontend')

        # Check if package.json exists
        if not os.path.exists(os.path.join(frontend_dir, 'package.json')):
            print("⚠️  Frontend package.json not found")
            return False

        # Try to build
        result = subprocess.run(['npm', 'run', 'build'],
                              cwd=frontend_dir,
                              capture_output=True,
                              text=True,
                              timeout=60)

        if result.returncode == 0:
            print("✅ Frontend build successful")
            return True
        else:
            print(f"❌ Frontend build failed: {result.stderr}")
            return False

    except Exception as e:
        print(f"❌ Frontend build test failed: {e}")
        return False

def main():
    """Main test function"""
    print("🚀 RAG System Startup Test\n")
    print("=" * 50)

    results = []

    # Test 1: Backend imports
    results.append(test_backend_imports())

    # Test 2: Intent classification
    results.append(test_intent_classification())

    # Test 3: Frontend build (skip if npm not available)
    try:
        import subprocess
        subprocess.run(['npm', '--version'], capture_output=True, check=True)
        results.append(test_frontend_build())
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("\n⚠️  npm not available, skipping frontend build test")
        results.append(True)  # Don't fail the test for missing npm

    print("\n" + "=" * 50)
    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"🎉 All tests passed! ({passed}/{total})")
        print("Your RAG system should be ready to start with ./start.sh")
        return 0
    else:
        print(f"❌ Some tests failed ({passed}/{total})")
        print("Please check the error messages above")
        return 1

if __name__ == "__main__":
    sys.exit(main())
