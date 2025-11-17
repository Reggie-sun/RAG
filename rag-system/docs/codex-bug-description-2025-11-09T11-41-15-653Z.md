RAG系统前端404错误修复

问题描述：
前端在调用 `/api/index/status` 接口时出现404错误。

问题分析：
1. 后端有两个服务运行在8000和8001端口
2. 前端配置VITE_CPU_API_BASE_URL=http://localhost:8001
3. 前端使用cpuClient调用/api/index/status接口
4. 实际请求URL应该是http://localhost:8001/api/index/status
5. 但是/api/index/status路由在backend/cpu_tasks_app.py中可能没有正确定义

主要文件：
- /home/reggie/vscode_folder/RAG/rag-system/frontend/src/services/api.ts (第26-29行)
- /home/reggie/vscode_folder/RAG/rag-system/backend/cpu_tasks_app.py
- /home/reggie/vscode_folder/RAG/rag-system/backend/routers/status.py (第58-60行)

期望修复：
确保前端能够成功调用/api/index/status接口获取索引状态信息，不再出现404错误。

技术细节：
- 前端使用axios cpuClient，baseURL为VITE_CPU_API_BASE_URL (http://localhost:8001)
- 接口应该返回IndexStatus类型的数据：{documents: number, chunks: number, updated_at: string}
- 需要确保CPU任务应用正确包含了status路由器

---
REQUIREMENTS AFTER FIX:

1. Create a detailed fix report in docs/ directory: docs/codex-fix-2025-11-09T11-41-15-653Z.md

2. The report MUST use the following Markdown format:

# Bug Fix Report

## Problem Description
RAG系统前端404错误修复

问题描述：
前端在调用 `/api/index/status` 接口时出现404错误。

问题分析：
1. 后端有两个服务运行在8000和8001端口
2. 前端配置VITE_CPU_API_BASE_URL=http://localhost:8001
3. 前端使用cpuClient调用/api/index/status接口
4. 实际请求URL应该是http://localhost:8001/api/index/status
5. 但是/api/index/status路由在backend/cpu_tasks_app.py中可能没有正确定义

主要文件：
- /home/reggie/vscode_folder/RAG/rag-system/frontend/src/services/api.ts (第26-29行)
- /home/reggie/vscode_folder/RAG/rag-system/backend/cpu_tasks_app.py
- /home/reggie/vscode_folder/RAG/rag-system/backend/routers/status.py (第58-60行)

期望修复：
确保前端能够成功调用/api/index/status接口获取索引状态信息，不再出现404错误。

技术细节：
- 前端使用axios cpuClient，baseURL为VITE_CPU_API_BASE_URL (http://localhost:8001)
- 接口应该返回IndexStatus类型的数据：{documents: number, chunks: number, updated_at: string}
- 需要确保CPU任务应用正确包含了status路由器

## Fix Time
2025-11-09T11:41:15.653Z

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
Report generated: 2025-11-09T11:41:15.653Z
Fix tool: OpenAI Codex
