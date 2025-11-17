Fix compilation errors in RAG system backend and frontend

PROBLEM DESCRIPTION:
Multiple compilation and runtime errors in the hybrid RAG system:

BACKEND ERRORS:
1. Module import errors in providers.py - circular import issues
2. Missing Optional import in enhanced_intent_classifier.py 
3. JSON serialization/safety issues in intent classification
4. Async context manager errors in web search service
5. Missing method calls in rag_service.py

FRONTEND ERRORS:
1. TypeScript compilation errors in ui components
2. Missing dependencies for Radix UI components
3. Build configuration issues with Vite
4. Import path resolution problems

SPECIFIC ERRORS TO FIX:
- providers.py: Fix import dependency cycle
- enhanced_intent_classifier.py: Fix JSON escaping and parameter validation
- web_search_service.py: Fix async result normalization 
- rag_service.py: Fix missing method calls and async context issues
- Frontend: Resolve TypeScript build errors and missing dependencies
- Fix all import path resolution issues
- Ensure all async/await patterns are correctly implemented

EXPECTED BEHAVIOR:
- Backend services should compile without import or syntax errors
- Frontend should build successfully with TypeScript
- All async operations should have proper error handling
- No circular import dependencies
- All new UI components should render correctly
- System should maintain all existing functionality

FILES TO CHECK:
- rag-system/backend/services/providers.py
- rag-system/backend/services/enhanced_intent_classifier.py
- rag-system/backend/services/web_search_service.py
- rag-system/backend/services/rag_service.py
- rag-system/frontend/src/components/ui/progress.tsx
- rag-system/frontend/src/components/ui/tooltip.tsx
- rag-system/frontend/src/components/answer/answer-panel.tsx
- rag-system/frontend/src/App.tsx
- rag-system/frontend/package.json
- rag-system/frontend/tsconfig.node.json

TEST CASES:
1. Backend should start without import errors
2. Frontend build should complete successfully (`npm run build`)
3. All TypeScript types should be resolved
4. Hybrid retrieval functionality should work correctly
5. UI components should render without errors

CONTEXT:
This is a production-ready hybrid RAG system with intent classification, web search integration, and advanced UI components. The errors are preventing the system from running properly and need to be resolved for deployment.

---
REQUIREMENTS AFTER FIX:

1. Create a detailed fix report in docs/ directory: docs/codex-fix-2025-11-08T03-52-27-786Z.md

2. The report MUST use the following Markdown format:

# Bug Fix Report

## Problem Description
Fix compilation errors in RAG system backend and frontend

PROBLEM DESCRIPTION:
Multiple compilation and runtime errors in the hybrid RAG system:

BACKEND ERRORS:
1. Module import errors in providers.py - circular import issues
2. Missing Optional import in enhanced_intent_classifier.py 
3. JSON serialization/safety issues in intent classification
4. Async context manager errors in web search service
5. Missing method calls in rag_service.py

FRONTEND ERRORS:
1. TypeScript compilation errors in ui components
2. Missing dependencies for Radix UI components
3. Build configuration issues with Vite
4. Import path resolution problems

SPECIFIC ERRORS TO FIX:
- providers.py: Fix import dependency cycle
- enhanced_intent_classifier.py: Fix JSON escaping and parameter validation
- web_search_service.py: Fix async result normalization 
- rag_service.py: Fix missing method calls and async context issues
- Frontend: Resolve TypeScript build errors and missing dependencies
- Fix all import path resolution issues
- Ensure all async/await patterns are correctly implemented

EXPECTED BEHAVIOR:
- Backend services should compile without import or syntax errors
- Frontend should build successfully with TypeScript
- All async operations should have proper error handling
- No circular import dependencies
- All new UI components should render correctly
- System should maintain all existing functionality

FILES TO CHECK:
- rag-system/backend/services/providers.py
- rag-system/backend/services/enhanced_intent_classifier.py
- rag-system/backend/services/web_search_service.py
- rag-system/backend/services/rag_service.py
- rag-system/frontend/src/components/ui/progress.tsx
- rag-system/frontend/src/components/ui/tooltip.tsx
- rag-system/frontend/src/components/answer/answer-panel.tsx
- rag-system/frontend/src/App.tsx
- rag-system/frontend/package.json
- rag-system/frontend/tsconfig.node.json

TEST CASES:
1. Backend should start without import errors
2. Frontend build should complete successfully (`npm run build`)
3. All TypeScript types should be resolved
4. Hybrid retrieval functionality should work correctly
5. UI components should render without errors

CONTEXT:
This is a production-ready hybrid RAG system with intent classification, web search integration, and advanced UI components. The errors are preventing the system from running properly and need to be resolved for deployment.

## Fix Time
2025-11-08T03:52:27.786Z

## Modified Files
List all modified files with their full paths

## Detailed Changes
For each file, provide detailed explanation:

### File: filename
**Changes**: Brief description

**Before**:
```language
original code
```

**After**:
```language
new code
```

**Reason**: Why this change was made

## Testing Recommendations
1. Unit test commands
2. Manual testing steps
3. Expected results

## Notes
Important notes about these changes

## Summary
Summarize this fix in 1-2 sentences

---
Report generated: 2025-11-08T03:52:27.786Z
Fix tool: OpenAI Codex
