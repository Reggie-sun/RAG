Chinese font rendering fix needed for RAG frontend. Google Fonts Noto Sans SC is failing to load, causing font display issues.

PROBLEM:
- Google Fonts resource loading failure: https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;600;700&display=swap
- 200+ font entries with "unloaded" status for Noto Sans SC
- External font dependency causing loading issues and performance problems
- HTML language changed to zh-CN may cause browser behavior issues
- Chinese punctuation was incorrectly changed from full-width to half-width

ROOT CAUSE:
- External Google Fonts dependency is unreliable and failing to load
- Font loading failure causes poor Chinese text rendering
- Unnecessary changes to HTML language and punctuation that weren't needed
- Over-engineering the font solution instead of using system fonts

SUGGESTED FIX:
1. Remove Google Fonts dependency from HTML head
2. Revert HTML language from zh-CN back to en (keep original)
3. Use system font stack that works reliably without external dependencies
4. Restore Chinese punctuation to proper full-width format (， not ,)
5. Keep Tailwind config with system fonts but remove external font references
6. Ensure Chinese characters render properly using system fonts

RELATED FILES:
- /home/reggie/vscode_folder/RAG/rag-system/frontend/index.html (remove Google Fonts links)
- /home/reggie/vscode_folder/RAG/rag-system/frontend/tailwind.config.ts (use system fonts only)
- /home/reggie/vscode_folder/RAG/rag-system/frontend/src/index.css (remove external font references)
- /home/reggie/vscode_folder/RAG/rag-system/frontend/src/components/layout/header.tsx (restore full-width commas)
- /home/reggie/vscode_folder/RAG/rag-system/frontend/src/components/upload/enhanced-upload-card.tsx (restore full-width commas)
- /home/reggie/vscode_folder/RAG/rag-system/frontend/src/components/search/search-form.tsx (restore full-width commas)

TEST CASES:
- No external font loading errors in console
- Chinese characters should display properly with system fonts
- Page should load quickly without external dependencies
- Chinese punctuation should use proper full-width characters (，)
- No network requests to fonts.googleapis.com

---
REQUIREMENTS AFTER FIX:

1. Create a detailed fix report in docs/ directory: docs/codex-fix-2025-11-15T18-04-31-894Z.md

2. The report MUST use the following Markdown format:

# Bug Fix Report

## Problem Description
Chinese font rendering fix needed for RAG frontend. Google Fonts Noto Sans SC is failing to load, causing font display issues.

PROBLEM:
- Google Fonts resource loading failure: https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;600;700&display=swap
- 200+ font entries with "unloaded" status for Noto Sans SC
- External font dependency causing loading issues and performance problems
- HTML language changed to zh-CN may cause browser behavior issues
- Chinese punctuation was incorrectly changed from full-width to half-width

ROOT CAUSE:
- External Google Fonts dependency is unreliable and failing to load
- Font loading failure causes poor Chinese text rendering
- Unnecessary changes to HTML language and punctuation that weren't needed
- Over-engineering the font solution instead of using system fonts

SUGGESTED FIX:
1. Remove Google Fonts dependency from HTML head
2. Revert HTML language from zh-CN back to en (keep original)
3. Use system font stack that works reliably without external dependencies
4. Restore Chinese punctuation to proper full-width format (， not ,)
5. Keep Tailwind config with system fonts but remove external font references
6. Ensure Chinese characters render properly using system fonts

RELATED FILES:
- /home/reggie/vscode_folder/RAG/rag-system/frontend/index.html (remove Google Fonts links)
- /home/reggie/vscode_folder/RAG/rag-system/frontend/tailwind.config.ts (use system fonts only)
- /home/reggie/vscode_folder/RAG/rag-system/frontend/src/index.css (remove external font references)
- /home/reggie/vscode_folder/RAG/rag-system/frontend/src/components/layout/header.tsx (restore full-width commas)
- /home/reggie/vscode_folder/RAG/rag-system/frontend/src/components/upload/enhanced-upload-card.tsx (restore full-width commas)
- /home/reggie/vscode_folder/RAG/rag-system/frontend/src/components/search/search-form.tsx (restore full-width commas)

TEST CASES:
- No external font loading errors in console
- Chinese characters should display properly with system fonts
- Page should load quickly without external dependencies
- Chinese punctuation should use proper full-width characters (，)
- No network requests to fonts.googleapis.com

## Fix Time
2025-11-15T18:04:31.894Z

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
Report generated: 2025-11-15T18:04:31.894Z
Fix tool: OpenAI Codex
