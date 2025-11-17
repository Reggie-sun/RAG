Fix RAG system startup issues and optimize code logic

PROBLEM DESCRIPTION:
RAG system has startup issues due to code logic problems in core files. Need to fix and optimize the system to run properly.

MAIN ISSUES TO FIX:

1. **rag_service.py (MAIN FILE)**:
   - Async/await context issues in mixed retrieval logic
   - Missing method implementations for _generate_structured_answer
   - Incorrect method calls and parameter passing
   - Multi-topic processing logic errors
   - Type annotation issues causing import problems

2. **answer-panel.tsx (MAIN FILE)**:
   - TypeScript compilation errors with new interfaces
   - Missing component props and type mismatches
   - UI component integration issues
   - State management problems for hybrid features

3. **SUPPORTING FILES TO OPTIMIZE**:
   - enhanced_intent_classifier.py: JSON parsing and async issues
   - web_search_service.py: Result normalization problems
   - providers.py: Import dependency cycles
   - API types: Interface alignment issues

SPECIFIC ERRORS TO RESOLVE:
- Missing _generate_structured_answer method in RAGService
- Incorrect async context managers in web search
- Type mismatches between frontend and backend interfaces
- Missing error handling in multi-topic processing
- Component prop type issues in React components
- Import circular dependencies in service providers

EXPECTED BEHAVIOR:
- Backend should start without import or runtime errors
- Frontend should compile and render successfully
- All hybrid RAG functionality should work (intent classification, web search, multi-topic)
- System should handle different question types correctly
- UI should display search results, citations, and diagnostics properly
- No TypeScript compilation errors
- All async operations should have proper error handling

FILES TO CHECK AND FIX:
- rag-system/backend/services/rag_service.py (PRIMARY)
- rag-system/frontend/src/components/answer/answer-panel.tsx (PRIMARY)
- rag-system/backend/services/enhanced_intent_classifier.py
- rag-system/backend/services/web_search_service.py
- rag-system/backend/services/providers.py
- rag-system/frontend/src/types/api.ts
- Any other files causing startup issues

CONTEXT:
This is a hybrid RAG system with intent classification, web search integration (Tavily API), and multi-topic processing. The system should be able to:
1. Analyze question intent (fact, how_to, comparison, decision, general)
2. Route to appropriate answering mode (document_first, hybrid, general_only)
3. Combine document retrieval with web search when needed
4. Handle multi-topic questions with parallel processing
5. Display results with proper citations and source attribution

The main goal is to get the startup scripts working properly with all functionality operational.

---
REQUIREMENTS AFTER FIX:

1. Create a detailed fix report in docs/ directory: docs/codex-fix-2025-11-08T14-25-30-293Z.md

2. The report MUST use the following Markdown format:

# Bug Fix Report

## Problem Description
Fix RAG system startup issues and optimize code logic

PROBLEM DESCRIPTION:
RAG system has startup issues due to code logic problems in core files. Need to fix and optimize the system to run properly.

MAIN ISSUES TO FIX:

1. **rag_service.py (MAIN FILE)**:
   - Async/await context issues in mixed retrieval logic
   - Missing method implementations for _generate_structured_answer
   - Incorrect method calls and parameter passing
   - Multi-topic processing logic errors
   - Type annotation issues causing import problems

2. **answer-panel.tsx (MAIN FILE)**:
   - TypeScript compilation errors with new interfaces
   - Missing component props and type mismatches
   - UI component integration issues
   - State management problems for hybrid features

3. **SUPPORTING FILES TO OPTIMIZE**:
   - enhanced_intent_classifier.py: JSON parsing and async issues
   - web_search_service.py: Result normalization problems
   - providers.py: Import dependency cycles
   - API types: Interface alignment issues

SPECIFIC ERRORS TO RESOLVE:
- Missing _generate_structured_answer method in RAGService
- Incorrect async context managers in web search
- Type mismatches between frontend and backend interfaces
- Missing error handling in multi-topic processing
- Component prop type issues in React components
- Import circular dependencies in service providers

EXPECTED BEHAVIOR:
- Backend should start without import or runtime errors
- Frontend should compile and render successfully
- All hybrid RAG functionality should work (intent classification, web search, multi-topic)
- System should handle different question types correctly
- UI should display search results, citations, and diagnostics properly
- No TypeScript compilation errors
- All async operations should have proper error handling

FILES TO CHECK AND FIX:
- rag-system/backend/services/rag_service.py (PRIMARY)
- rag-system/frontend/src/components/answer/answer-panel.tsx (PRIMARY)
- rag-system/backend/services/enhanced_intent_classifier.py
- rag-system/backend/services/web_search_service.py
- rag-system/backend/services/providers.py
- rag-system/frontend/src/types/api.ts
- Any other files causing startup issues

CONTEXT:
This is a hybrid RAG system with intent classification, web search integration (Tavily API), and multi-topic processing. The system should be able to:
1. Analyze question intent (fact, how_to, comparison, decision, general)
2. Route to appropriate answering mode (document_first, hybrid, general_only)
3. Combine document retrieval with web search when needed
4. Handle multi-topic questions with parallel processing
5. Display results with proper citations and source attribution

The main goal is to get the startup scripts working properly with all functionality operational.

## Fix Time
2025-11-08T14:25:30.293Z

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
Report generated: 2025-11-08T14:25:30.293Z
Fix tool: OpenAI Codex
